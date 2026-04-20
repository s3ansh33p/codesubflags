from flask import Blueprint, request # only needed for Blueprint import
from flask_restx import Namespace, Resource

from CTFd.models import (
    ChallengeFiles,
    Challenges,
    Fails,
    Flags,
    Hints,
    Solves,
    Tags,
    db,
    Awards,
)

import re
import requests
import os 

from CTFd.utils.uploads import delete_file #to delete challenge files
from CTFd.utils.decorators import admins_only, authed_only
from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
from CTFd.plugins.migrations import upgrade
from CTFd.api import CTFd_API_v1
from CTFd.utils.config import is_teams_mode
from CTFd.utils.user import get_current_team, get_current_user
from datetime import datetime

RUNNER_URL = os.environ.get("RUNNER_URL", "http://piston_api:2000/api/v2/execute")

DEFAULT_HISTORY_SIZE = 10
MAX_HISTORY_CAP = 500

def _history_size(challenge):
    size = challenge.history_size
    return size if size is not None else DEFAULT_HISTORY_SIZE


def _effective_retention(size):
    # Translate the admin-facing history_size contract into a row count to keep:
    #   -1 -> 0 (disabled, nothing persisted)
    #    0 -> MAX_HISTORY_CAP (unlimited, bounded by safety cap)
    #    N -> min(N, MAX_HISTORY_CAP)
    if size == -1:
        return 0
    if size == 0:
        return MAX_HISTORY_CAP
    return min(size, MAX_HISTORY_CAP)

# database mdoel for the codesubflag challenge model
class CodesubflagChallenge(Challenges):
    __mapper_args__ = {"polymorphic_identity": "codesubflags"}
    id = db.Column(db.Integer,
        db.ForeignKey("challenges.id", ondelete="CASCADE"),
        primary_key=True)
    run_timeout = db.Column(db.Integer, default=5000)
    run_file = db.Column(db.String(128)) # template/starter code given to the user
    data_file = db.Column(db.String(128)) # for txt or csv
    # Server-side run history retention per user.
    #   -1 -> disabled (no server logging; localStorage only)
    #    0 -> unlimited
    #    N -> keep only the most recent N attempts per user
    history_size = db.Column(db.Integer, default=DEFAULT_HISTORY_SIZE)


# Records every Run-click submission so a user can restore prior code if they
# misclick/navigate away. Per-user history (not team-shared) so teammates
# don't see each other's in-progress drafts. Governed by
# CodesubflagChallenge.history_size.
class CodesubflagAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer,
        db.ForeignKey("challenges.id", ondelete="CASCADE"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    code = db.Column(db.Text)
    stdout = db.Column(db.Text, nullable=True)
    stderr = db.Column(db.Text, nullable=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)

    # Per-user history lookup with ordering — without this, prune/list scales
    # as O(n) in the user's cumulative run count.
    __table_args__ = (
        db.Index(
            "ix_codesubflag_attempt_user_challenge_date",
            "challenge_id",
            "user_id",
            "date",
        ),
    )

# database model for the individual codesubflag
# includes: id, reference to the associated challenge, desc, key (solution), order
class Codesubflags(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    challenge_id = db.Column(db.Integer, 
        db.ForeignKey("challenges.id", ondelete="CASCADE"))
    codesubflag_name = db.Column(db.String(128))
    codesubflag_desc = db.Column(db.String(128))
    codesubflag_placeholder = db.Column(db.String(128))
    codesubflag_key = db.Column(db.String(128))
    codesubflag_order = db.Column(db.Integer)
    codesubflag_points = db.Column(db.Integer)


    def __init__(self, challenge_id, codesubflag_name, codesubflag_desc, codesubflag_placeholder, codesubflag_key, codesubflag_order, codesubflag_points):
        self.challenge_id = challenge_id
        self.codesubflag_name = codesubflag_name
        self.codesubflag_desc = codesubflag_desc
        self.codesubflag_placeholder = codesubflag_placeholder
        self.codesubflag_key = codesubflag_key
        self.codesubflag_order = codesubflag_order
        self.codesubflag_points = codesubflag_points


# database mdoel for the team solves of a codesubflag
# constraints: unique combination of codesubflag id and team id
# includes: id, reference to the associated codesubflag, team id and solve timestamp
class CodesubflagSolve(db.Model):
    __table_args__ = (db.UniqueConstraint('codesubflag_id', 'team_id'), )
    id = db.Column(db.Integer, primary_key = True)
    codesubflag_id = db.Column(db.Integer, 
        db.ForeignKey('codesubflags.id', ondelete="CASCADE"))
    team_id = db.Column(db.Integer)
    date = db.Column(db.DateTime, default = datetime.utcnow)

    def __init__(self, codesubflag_id, team_id, user_id):
        self.codesubflag_id = codesubflag_id
        self.team_id = team_id
        self.user_id = user_id

# database model for the codesubflag hints
# constraint: hint id (hint can not be attached to multiple codesubflags)
# includes: reference to hint id, reference to codesubflag id, codesubflag order
class CodesubflagHint(db.Model):
    id = db.Column(db.Integer, db.ForeignKey('hints.id', ondelete="CASCADE"), primary_key = True)
    codesubflag_id = db.Column(db.Integer, db.ForeignKey('codesubflags.id', ondelete="CASCADE"))
    hint_order = db.Column(db.Integer)

    def __init__(self, id, codesubflag_id, hint_order):
        self.id = id
        self.codesubflag_id = codesubflag_id
        self.hint_order = hint_order

#describes the challenge type 
class CodesubflagChallengeType(BaseChallenge):
    # defines id and name of the codesubflag
    id = "codesubflags"
    name = "codesubflags"

    # locations of the html templates
    templates = {  # Handlebars templates used for each aspect of challenge editing & viewing
        'create': '/plugins/codesubflags/assets/create.html',
        'update': '/plugins/codesubflags/assets/update.html',
        'view': '/plugins/codesubflags/assets/view.html',
    }

    # location of the JavaScript files
    scripts = {  # Scripts that are loaded when a template is loaded
        'create': '/plugins/codesubflags/assets/create.js',
        'update': '/plugins/codesubflags/assets/update.js',
        'view': '/plugins/codesubflags/assets/view.js',
    }
    route = '/plugins/codesubflags/assets'

    # flask blueprint location
    blueprint = Blueprint(
        "dynamic_challenges",
        __name__,
        template_folder="templates",
        static_folder="assets",
    )
    challenge_model = CodesubflagChallenge

    # overrides the default function to create a challenge
    @classmethod
    def create(cls, request):
        """
        This method is used to process the challenge creation request.

        :param request:
        :return:
        """
        # input data
        data = request.form or request.get_json()

        # get list with only challenge information (no information about codesubflags and their hints)
        challenge_data = {key:value for (key,value) in data.items() if not key.startswith('codesubflag')}

        # create new Codesubflag challenge with all ordinary challenge information (excluding codesubflag data)
        challenge = CodesubflagChallenge(**challenge_data)
        db.session.add(challenge)
        db.session.commit()

        # get list with only codesubflag information 
        codesubflag_data = {key:value for (key,value) in data.items() if key.startswith('codesubflag')}
        
        # creates an array to save the codesubflag information in
        codesubflag_data_list = []

        # the number of attributes associated with each codesubflag
        num_items = 6

        # tranfers the codesubflag data to a array
        for key in codesubflag_data:
            codesubflag_data_list.append(codesubflag_data[key])

        # iterates over the array taking into consideration the number of attributes each codesubflag has
        for num in range(int(len(codesubflag_data_list) / num_items)):
            # if the codesubflag has an empty field dont create it
            if (len(codesubflag_data_list[num_items*num]) == 0 or len(codesubflag_data_list[num_items*num+3]) == 0) or codesubflag_data_list[num_items*num+4] is None:
                break
            else:
                # if all fields are filled out create a codesubflag
                codesubflag = Codesubflags(
                    challenge_id = challenge.id,
                    codesubflag_name = codesubflag_data_list[num_items*num],
                    codesubflag_desc = codesubflag_data_list[num_items*num+1],
                    codesubflag_placeholder = codesubflag_data_list[num_items*num+2],
                    codesubflag_key = codesubflag_data_list[num_items*num+3],
                    codesubflag_order = codesubflag_data_list[num_items*num+4],
                    codesubflag_points = codesubflag_data_list[num_items*num+5]
                )
                db.session.add(codesubflag)
                db.session.commit()        
        return challenge

    # override the default function to delete a challenge
    @classmethod
    def delete(cls, challenge):
        """
        This method is used to delete the resources used by a challenge.
        :param challenge:
        :return:
        """
        # gets a list of all codesubflags associated to the challenge
        codesubflags = Codesubflags.query.filter_by(challenge_id = challenge.id).all()
        for codesubflag in codesubflags:
            # deletes all solves and hints associated with the codesubflag
            CodesubflagSolve.query.filter_by(codesubflag_id = codesubflag.id).delete()
            CodesubflagHint.query.filter_by(codesubflag_id = codesubflag.id).delete()

        # delete all codesubflags of the challenge
        Codesubflags.query.filter_by(challenge_id=challenge.id).delete()

        # delete all code-run history entries for the challenge
        CodesubflagAttempt.query.filter_by(challenge_id=challenge.id).delete()

        # delete all ordinary challenge files
        Fails.query.filter_by(challenge_id=challenge.id).delete()
        Solves.query.filter_by(challenge_id=challenge.id).delete()
        Flags.query.filter_by(challenge_id=challenge.id).delete()
        files = ChallengeFiles.query.filter_by(challenge_id=challenge.id).all()
        for f in files:
            delete_file(f.id)
        ChallengeFiles.query.filter_by(challenge_id=challenge.id).delete()
        Tags.query.filter_by(challenge_id=challenge.id).delete()
        Hints.query.filter_by(challenge_id=challenge.id).delete()
        CodesubflagChallenge.query.filter_by(id=challenge.id).delete()
        Challenges.query.filter_by(id=challenge.id).delete()
        db.session.commit()


# API Extensions for Codesubflags

# endpoint to attach a codesubflag to a challenge
# inputs: challenge_id, codesubflag_desc, codesubflag_key, codesubflag_order

codesubflags_namespace = Namespace("codesubflags", description="Endpoint retrieve codesubflags")


def _hint_order_map(codesubflag_id):
    hints = CodesubflagHint.query.filter_by(codesubflag_id=codesubflag_id).all()
    return {h.id: {"order": h.hint_order} for h in hints}


def _serialize_codesubflag(cs, *, include_key=False, solved=None):
    data = {
        "desc": cs.codesubflag_desc,
        "placeholder": cs.codesubflag_placeholder,
        "order": cs.codesubflag_order,
        "points": cs.codesubflag_points,
        "hints": _hint_order_map(str(cs.id)),
    }
    if include_key:
        # Admin-only view — safe to expose the answer key and name.
        data["name"] = cs.codesubflag_name
        data["key"] = cs.codesubflag_key
    if solved is not None:
        data["solved"] = solved
    return data

@codesubflags_namespace.route("")
class Codesubflag(Resource):
    """
	The Purpose of this API Endpoint is to allow an admin to add a single codesubflag to a challenge
	"""
    # user has to be authentificated as admin to call this endpoint    
    @admins_only
    def post(self):
        # parses request arguements into data
        if request.content_type != "application/json":
            data = request.form
        else:
            data = request.get_json()

        if (data["challenge_id"] and data["codesubflag_name"] and data["codesubflag_desc"] and data["codesubflag_key"] and data["codesubflag_points"]  and data["codesubflag_order"] is not None):
            # creates new entry in Codesubflag table with the request arguments
            codesubflag = Codesubflags(
                challenge_id = data["challenge_id"],
                codesubflag_name = data["codesubflag_name"],
                codesubflag_desc = data["codesubflag_desc"],
                codesubflag_placeholder = data["codesubflag_placeholder"],
                codesubflag_key = data["codesubflag_key"],
                codesubflag_order = data["codesubflag_order"],
                codesubflag_points = data["codesubflag_points"],
            )                
            db.session.add(codesubflag)
            db.session.commit()
            
            return {"success": True, "data": {"message": "New codesubflag created"}}
        else:
            return {"success": False, "data": {"message": "at least one input empty"}}

@codesubflags_namespace.route("/<codesubflag_id>")
class Codesubflag(Resource):
    """
    The Purpose of this API Endpoint is to allow an admin to update a single codesubflag
    """
    @admins_only
    def patch(self, codesubflag_id):
        # parse request arguments
        data = request.get_json()
        # get codesubflag from database
        codesubflag = Codesubflags.query.filter_by(id = codesubflag_id).first()

        # update codesubflag data entries if the entry field are not empty 
        if len(data["codesubflag_name"]) != 0:
            codesubflag.codesubflag_name = data["codesubflag_name"]
        if len(data["codesubflag_desc"]) != 0:
            codesubflag.codesubflag_desc = data["codesubflag_desc"]   
        if len(data["codesubflag_placeholder"]) != 0:
            codesubflag.codesubflag_placeholder = data["codesubflag_placeholder"]        
        if len(data["codesubflag_key"]) != 0:
            codesubflag.codesubflag_key = data["codesubflag_key"]
        number = int(data["codesubflag_order"])
        if isinstance(number, int):
            codesubflag.codesubflag_order = number

        number2 = int(data["codesubflag_points"])
        if isinstance(number2, int):
            codesubflag.codesubflag_points = number2

        db.session.add(codesubflag)
        db.session.commit()

        return {"success": True, "data": {"message": "sucessfully updated"}}


    """
    The Purpose of this API Endpoint is to allow admins to delete a codesubflag
    """
    # user has to be authentificated as admin to call this endpoint
    @admins_only
    def delete(self, codesubflag_id):

        # delete associated hints, solved and the codesubflag itself
        CodesubflagHint.query.filter_by(codesubflag_id = codesubflag_id).delete()
        CodesubflagSolve.query.filter_by(codesubflag_id = codesubflag_id).delete()
        Codesubflags.query.filter_by(id = codesubflag_id).delete()

        db.session.commit()

        return {"success": True, "data": {"message": "Codesubflag deleted"}}

@codesubflags_namespace.route("/challenges/<chal_id>/update")
class Updates(Resource):
    """
	The Purpose of this API Endpoint is to allow an admin to view the Codesubflags (including the key) in the upgrade screen
	"""
    # user has to be authentificated as admin to call this endpoint
    @admins_only
    def get(self, chal_id):
        codesubflag_data = Codesubflags.query.filter_by(challenge_id=chal_id).all()
        return {
            str(cs.id): _serialize_codesubflag(cs, include_key=True)
            for cs in codesubflag_data
        }

@codesubflags_namespace.route("/hints/<hint_id>")
class Hint(Resource):
    """
    The Purpose of this API Endpoint is to allow admins to attach a hint to a specific codesubflag
    """
    # user has to be authentificated as admin to call this endpoint
    @admins_only
    def post(self, hint_id):
        #parse request arguements
        data = request.get_json()

        # creates new entry in codesubflag hint database
        codesubflag_hint = CodesubflagHint(
            id = hint_id,
            codesubflag_id = data["codesubflag_id"],
            hint_order = data["hint_order"],
        )
        db.session.add(codesubflag_hint)
        db.session.commit()
        return {"success": True, "data": {"message": "Hint attached"}}


    """
    The Purpose of this API Endpoint is to allow admins to delete a hint from a specific codesubflag
    """
    # user has to be authentificated as admin to call this endpoint
    @admins_only
    def delete(self, hint_id):
        # deletes codesubflag hint 
        CodesubflagHint.query.filter_by(id = hint_id).delete()
        db.session.commit()
        return {"success": True, "data": {"message": "Codesubflag removed"}}

@codesubflags_namespace.route("/challenges/<chal_id>/view")
class Views(Resource):
    """
	The Purpose of this API Endpoint is to allow an user to see the codesubflags when solving a challenge. 
	"""
    # user has to be authentificated to call this endpoint
    @authed_only
    def get(self, chal_id):
        team = get_current_team()
        team_id = team.id if team else None
        codesubflag_data = Codesubflags.query.filter_by(challenge_id=chal_id).all()
        result = {}
        for cs in codesubflag_data:
            solved = CodesubflagSolve.query.filter_by(
                codesubflag_id=str(cs.id), team_id=team_id
            ).first() is not None
            result[str(cs.id)] = _serialize_codesubflag(cs, solved=solved)
        return result

@codesubflags_namespace.route("/solve/<codesubflag_id>")
class Solve(Resource):
    """
	The Purpose of this API Endpoint is to allow an user to post a solve atempt. 
	"""
    # user has to be authentificated to call this endpoint
    @authed_only
    def post(self, codesubflag_id):
        # parse request arguements 
        data = request.get_json()

        # pulls the right key from the database
        right_key = Codesubflags.query.filter_by(id = codesubflag_id).first()
        
        # if the key is not right return an error message
        if right_key.codesubflag_key != data["answer"]:
            return {"success": True, "data": {"message": "False Attempt", "solved": False}}

        #  if the challenge was already solved return a error message
        team = get_current_team()
        if not team:
            solved = CodesubflagSolve.query.filter_by(codesubflag_id = codesubflag_id, team_id = None).first() is not None
        else:
            solved = CodesubflagSolve.query.filter_by(codesubflag_id = codesubflag_id, team_id = team.id).first() is not None
        if solved:
            return {"success": True, "data": {"message": "was already solved", "solved": True}}

        # if the key is correct and the flag was not already solved
        # add solve to database and return true
        user = get_current_user()
        team_id = team.id if team is not None else None
        solve = CodesubflagSolve(
            codesubflag_id=codesubflag_id,
            user_id=user.id,
            team_id=team_id,
        )
        award = Awards(
            name=right_key.codesubflag_name,
            user_id=user.id,
            team_id=team_id,
            value=right_key.codesubflag_points,
        )
        db.session.add(solve)
        db.session.add(award)
        db.session.commit()
        return {"success": True, "data": {"message": "Codesubflag solved", "solved": True}}

def getContents(fileToConvert):
    fullpath = os.path.join(os.path.dirname(__file__), "challenge_files", fileToConvert)
    # get contents and convert to string
    data = "";
    with open(fullpath, 'r') as file:
        data = file.read()
        # remove all comments
        # data = re.sub(r'#.*', '', data)
        # remove all blank lines
        # data = re.sub(r'\n\s*\n', '\n', data)
    return data   

@codesubflags_namespace.route("/run/<challenge_id>")
class Run(Resource):
    """
    The Purpose of this API Endpoint is to allow participants to run code
    """

    # user has to be authentificated to call this endpoint
    @authed_only
    def post(self, challenge_id):
        try:
            data = request.get_json()
        except Exception as e:
            return {"success": False, "data": {"message": e}}


        challenge = CodesubflagChallenge.query.filter_by(id = challenge_id).first()
        if challenge is None:
            return {"success": False, "data": {"message": "Challenge not found"}}
        
        submission = data["submission"].strip()
        # instance_id = submission

        files = [{
            "name": "user.py",
            "content": submission
        }]
        if challenge.data_file:
            files.append({
                "name": challenge.data_file,
                "content": getContents(challenge.data_file)
            })

        try:
            r = requests.post(
                RUNNER_URL,
                json={
                    "language": "python3",
                    "version": "3.10.0",
                    "files": files, 
                    "run_timeout": challenge.run_timeout,
                    "stdin": "",
                    "args": [],
                },
            )
        except requests.exceptions.ConnectionError:
            return {"success": False, "data": {"message": "Challenge oracle is not available. Talk to an admin."}}

        if r.status_code == 200:
            payload = r.json()
            _record_attempt(challenge, submission, payload)
            return {"success": True, "data": payload}
        else:
            return {"success": False, "data": {"message": "Non 200 code returned. Talk to an admin."}}


def _record_attempt(challenge, submission, runner_payload):
    retention = _effective_retention(_history_size(challenge))
    if retention == 0:
        return
    user = get_current_user()
    if user is None:
        return
    run_block = runner_payload.get("run") or {}
    attempt = CodesubflagAttempt(
        challenge_id=challenge.id,
        user_id=user.id,
        code=submission,
        stdout=run_block.get("output"),
        stderr=run_block.get("stderr"),
    )
    db.session.add(attempt)
    db.session.commit()

    stale = (
        CodesubflagAttempt.query
        .filter_by(challenge_id=challenge.id, user_id=user.id)
        .order_by(CodesubflagAttempt.date.desc())
        .offset(retention)
        .all()
    )
    if stale:
        for row in stale:
            db.session.delete(row)
        db.session.commit()

@codesubflags_namespace.route("/get/<challenge_id>")
class Get(Resource):
    """
    The Purpose of this API Endpoint is to allow participants to get the starting code
    """

    # user has to be authentificated to call this endpoint
    @authed_only
    def get(self, challenge_id):
        challenge = CodesubflagChallenge.query.filter_by(id = challenge_id).first()
        if challenge is None:
            return {"success": False, "data": {"message": "Challenge not found"}}
        
        history_size = _history_size(challenge)
        if challenge.run_file:
            return {
                "success": True,
                "data": {
                    "message": getContents(challenge.run_file),
                    "history_size": history_size,
                },
            }
        else:
            return {"success": False, "data": {"message": "No starting code found. Talk to an admin."}}


@codesubflags_namespace.route("/attempts/<challenge_id>")
class Attempts(Resource):
    """
    Returns the calling user's saved code attempts for this challenge so the
    UI can restore previous runs. Newest first.
    """

    @authed_only
    def get(self, challenge_id):
        challenge = CodesubflagChallenge.query.filter_by(id=challenge_id).first()
        if challenge is None:
            return {"success": False, "data": {"message": "Challenge not found"}}

        size = _history_size(challenge)
        retention = _effective_retention(size)
        if retention == 0:
            return {"success": True, "data": {"history_size": size, "attempts": []}}

        user = get_current_user()
        if user is None:
            return {"success": False, "data": {"message": "Not authenticated"}}

        rows = (
            CodesubflagAttempt.query
            .filter_by(challenge_id=challenge.id, user_id=user.id)
            .order_by(CodesubflagAttempt.date.desc())
            .limit(retention)
            .all()
        )
        return {
            "success": True,
            "data": {
                "history_size": size,
                "attempts": [
                    {
                        "id": r.id,
                        "date": r.date.isoformat() if r.date else None,
                        "code": r.code,
                        "stdout": r.stdout,
                        "stderr": r.stderr,
                    }
                    for r in rows
                ],
            },
        }

def load(app):
    upgrade()
    app.db.create_all()
    CHALLENGE_CLASSES["codesubflags"] = CodesubflagChallengeType
    register_plugin_assets_directory(app, base_path="/plugins/codesubflags/assets/")
    # Expose the default so admin HTML forms don't have to hardcode it.
    app.jinja_env.globals["CODESUBFLAGS_DEFAULT_HISTORY_SIZE"] = DEFAULT_HISTORY_SIZE
    # creates all necessairy endpoints
    CTFd_API_v1.add_namespace(codesubflags_namespace, '/codesubflags')
