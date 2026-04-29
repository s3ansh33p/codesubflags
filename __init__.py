from flask import Blueprint, abort, current_app, render_template, request, send_from_directory, url_for # only needed for Blueprint import
from flask_restx import Namespace, Resource
from werkzeug.utils import secure_filename

from CTFd.models import (
    ChallengeFiles,
    Challenges,
    Fails,
    Flags,
    Hints,
    Solves,
    Tags,
    Users,
    db,
    Awards,
)

import json
import re
import requests
import os

from CTFd.utils.uploads import delete_file #to delete challenge files
from CTFd.utils.decorators import admins_only, authed_only
from CTFd.plugins import register_plugin_assets_directory, register_admin_plugin_script
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
from CTFd.plugins.migrations import upgrade
from CTFd.api import CTFd_API_v1
from CTFd.utils.config import is_teams_mode
from CTFd.utils.user import get_current_team, get_current_user
from datetime import datetime, timezone

RUNNER_URL = os.environ.get("RUNNER_URL", "http://piston_api:2000/api/v2/execute")


def _piston_base_url():
    # Strip the "/execute" suffix (or any trailing slash) from RUNNER_URL so we
    # can synthesise sibling endpoints like /runtimes and /packages without
    # forcing admins to set three near-identical env vars.
    base = RUNNER_URL
    suffix = "/execute"
    if base.endswith(suffix):
        base = base[: -len(suffix)]
    return base.rstrip("/")


RUNTIMES_URL = os.environ.get("RUNTIMES_URL", f"{_piston_base_url()}/runtimes")
PACKAGES_URL = os.environ.get("PACKAGES_URL", f"{_piston_base_url()}/packages")

DEFAULT_HISTORY_SIZE = 10
MAX_HISTORY_CAP = 500

# Shown to the user when a language row references a template that doesn't
# exist on disk, or when a challenge has no language rows configured.
NO_TEMPLATE_MESSAGE = "No starting code found. Talk to an admin."

# Piston accepts language/version names from a finite set; we never need
# anything outside this charset, so reject anything else early to avoid
# forwarding garbage into the proxy endpoints.
_LANG_VERSION_RE = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")


def _challenge_files_root():
    return os.path.realpath(os.path.join(os.path.dirname(__file__), "challenge_files"))


def _version_sort_key(version):
    # Lex-sort orders "3.10.0" before "3.9.0", which is the wrong reading for
    # most package managers. Split on ".", convert numeric segments to ints,
    # and fall back to the raw string for anything weird (e.g. "latest").
    parts = []
    for chunk in str(version or "").split("."):
        try:
            parts.append((0, int(chunk)))
        except ValueError:
            parts.append((1, chunk))
    return tuple(parts)


def _validated_lang_version(body):
    # Shared input check for the package install/uninstall handlers — keeps
    # garbage out of the piston request body and out of error messages.
    language = (body.get("language") or "").strip()
    version = (body.get("version") or "").strip()
    if not language or not version:
        return None, None, "language and version are required"
    if not _LANG_VERSION_RE.match(language) or not _LANG_VERSION_RE.match(version):
        return None, None, "language and version contain invalid characters"
    return language, version, None


def _safe_challenge_file_path(filename):
    # Resolve `filename` against challenge_files/ and ensure the result stays
    # under that directory. Filenames come from the admin languages editor;
    # without this check, a value like "../../etc/passwd" would let getContents
    # read arbitrary files on the host and serve them to participants.
    if not filename:
        raise ValueError("filename is required")
    base = _challenge_files_root()
    fullpath = os.path.realpath(os.path.join(base, filename))
    if fullpath != base and not fullpath.startswith(base + os.sep):
        raise ValueError("path escapes challenge_files")
    return fullpath


# Hard cap on a single uploaded file. Keeps a runaway upload from filling the
# host disk and matches the limit promised in the admin UI.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Extensions safe to load into the inline text editor. Anything outside this
# list is treated as binary and only available via Download/Delete/Rename.
_TEXT_FILE_EXTS = frozenset({
    ".py", ".java", ".txt", ".csv", ".md", ".json", ".log",
})

# Inline editor cap. Anything bigger should be edited offline and re-uploaded.
MAX_EDITABLE_BYTES = 1 * 1024 * 1024

# Directory and rename names: ASCII alnum plus . _ - only, no path separators.
_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _is_text_file(path):
    return os.path.splitext(path)[1].lower() in _TEXT_FILE_EXTS


def _safe_challenge_dir_path(relpath):
    # Same idea as _safe_challenge_file_path but tolerates the empty/"." case
    # by mapping it to the root itself. Used for directory-targeted endpoints
    # (list, upload-target, mkdir-parent).
    base = _challenge_files_root()
    rel = (relpath or "").strip().lstrip("/")
    if rel in ("", "."):
        return base
    fullpath = os.path.realpath(os.path.join(base, rel))
    if fullpath != base and not fullpath.startswith(base + os.sep):
        raise ValueError("path escapes challenge_files")
    return fullpath


def _relpath_under_root(fullpath):
    base = _challenge_files_root()
    if fullpath == base:
        return ""
    return os.path.relpath(fullpath, base).replace(os.sep, "/")

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


# One row per (challenge, language, version) the admin has attached. Each row
# carries its own template / data file so a single challenge can ship Python
# starter code, Java starter code, etc. Subflags stay shared across languages.
class CodesubflagChallengeLanguage(db.Model):
    __tablename__ = "codesubflag_challenge_languages"
    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(
        db.Integer,
        db.ForeignKey("challenges.id", ondelete="CASCADE"),
        nullable=False,
    )
    language = db.Column(db.String(64), nullable=False)
    version = db.Column(db.String(32), nullable=False)
    run_file = db.Column(db.String(128), nullable=False)
    data_file = db.Column(db.String(128), nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    __table_args__ = (
        db.Index("ix_csf_lang_challenge", "challenge_id"),
        db.UniqueConstraint(
            "challenge_id", "language", "version",
            name="uq_csf_lang_challenge_lv",
        ),
    )


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
    # Language/version the attempt ran against. Nullable so legacy rows from
    # the pre-multi-language schema continue to load.
    language = db.Column(db.String(64), nullable=True)
    version = db.Column(db.String(32), nullable=True)

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

def _pop_languages_payload(data):
    # The admin form posts a JSON-encoded list under "languages" (or, for
    # multipart submits, leaves it absent). Callers must pass a plain dict —
    # never an ImmutableMultiDict — so we can pop without try/except.
    raw = data.get("languages") if hasattr(data, "get") else None
    if raw is None:
        return None
    data.pop("languages", None)
    if isinstance(raw, str):
        if not raw.strip():
            return []
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return []
    if isinstance(raw, list):
        return raw
    return None


def _serialize_language(row):
    return {
        "id": row.id,
        "language": row.language,
        "version": row.version,
        "run_file": row.run_file,
        "data_file": row.data_file or "",
        "sort_order": row.sort_order or 0,
    }


def _replace_challenge_languages(challenge_id, payload):
    # payload=None means the form didn't include the field — leave existing
    # rows alone. payload=[] means "the admin cleared the list", which we
    # honour by deleting everything.
    if payload is None:
        return

    CodesubflagChallengeLanguage.query.filter_by(challenge_id=challenge_id).delete()
    for idx, entry in enumerate(payload):
        if not isinstance(entry, dict):
            continue
        language = (entry.get("language") or "").strip()
        version = (entry.get("version") or "").strip()
        run_file = (entry.get("run_file") or "").strip()
        if not (language and version and run_file):
            continue
        if not _LANG_VERSION_RE.match(language) or not _LANG_VERSION_RE.match(version):
            continue
        data_file = (entry.get("data_file") or "").strip() or None
        # Reject path-traversal attempts at write time so the on-disk reads in
        # /get and /run never have to second-guess what's stored in the DB.
        try:
            _safe_challenge_file_path(run_file)
            if data_file:
                _safe_challenge_file_path(data_file)
        except ValueError:
            continue
        sort_order = entry.get("sort_order")
        try:
            sort_order = int(sort_order) if sort_order is not None else idx
        except (TypeError, ValueError):
            sort_order = idx
        db.session.add(CodesubflagChallengeLanguage(
            challenge_id=challenge_id,
            language=language,
            version=version,
            run_file=run_file,
            data_file=data_file,
            sort_order=sort_order,
        ))
    db.session.commit()


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

        # languages is a JSON-encoded list of {language, version, run_file,
        # data_file, sort_order} rows posted by the admin form. Extract it
        # before passing the rest to the Challenge constructor so SQLAlchemy
        # doesn't see an unknown field.
        languages_payload = _pop_languages_payload(data)

        # get list with only challenge information (no information about codesubflags and their hints)
        challenge_data = {
            key: value
            for (key, value) in data.items()
            if not key.startswith('codesubflag') and key != 'languages'
        }

        # create new Codesubflag challenge with all ordinary challenge information (excluding codesubflag data)
        challenge = CodesubflagChallenge(**challenge_data)
        db.session.add(challenge)
        db.session.commit()

        _replace_challenge_languages(challenge.id, languages_payload)

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

    @classmethod
    def read(cls, challenge):
        # Extend the default payload with this challenge's configured
        # languages so the admin update.html can prefill the repeater
        # without a second round-trip. Use super() so type_data.id/name/
        # templates/scripts are taken from this subclass — calling
        # BaseChallenge.read directly would bind cls=BaseChallenge and
        # return an empty scripts dict, which the frontend would then try
        # to load as `<script src="undefined">`.
        data = super().read(challenge)
        rows = (
            CodesubflagChallengeLanguage.query
            .filter_by(challenge_id=challenge.id)
            .order_by(CodesubflagChallengeLanguage.sort_order)
            .all()
        )
        data["languages"] = [_serialize_language(r) for r in rows]
        return data

    @classmethod
    def update(cls, challenge, request):
        # CTFd's BaseChallenge.update setattr's every key on the model, so the
        # languages JSON has to be pulled off the request payload first.
        # request.form is an ImmutableMultiDict (a dict subclass) whose .pop
        # raises TypeError, so always materialise a plain mutable copy before
        # mutating it.
        source = request.form or request.get_json() or {}
        data = dict(source)
        languages_payload = _pop_languages_payload(data)

        # Saving an empty list would leave the challenge with zero languages
        # configured, which silently breaks /get and /run for participants.
        # Reject the save and let the admin re-submit with at least one row.
        if languages_payload == []:
            abort(400, "At least one language is required.")

        for attr, value in data.items():
            setattr(challenge, attr, value)
        db.session.commit()

        _replace_challenge_languages(challenge.id, languages_payload)
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

        # remove every language attached to the challenge
        CodesubflagChallengeLanguage.query.filter_by(challenge_id=challenge.id).delete()

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
    fullpath = _safe_challenge_file_path(fileToConvert)
    with open(fullpath, 'r') as file:
        return file.read()

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

        # Pick the language row to run against. If the client sent language+version
        # we trust that selection (after validating it's actually configured); if
        # they didn't and the challenge has exactly one row, fall back to it so
        # single-language challenges keep working without a body change.
        languages = (
            CodesubflagChallengeLanguage.query
            .filter_by(challenge_id=challenge.id)
            .order_by(CodesubflagChallengeLanguage.sort_order)
            .all()
        )
        if not languages:
            return {"success": False, "data": {"message": "No languages configured for this challenge."}}

        req_lang = (data.get("language") or "").strip()
        req_ver = (data.get("version") or "").strip()
        if req_lang and req_ver:
            lang_row = next(
                (l for l in languages if l.language == req_lang and l.version == req_ver),
                None,
            )
            if lang_row is None:
                return {"success": False, "data": {"message": "Selected language is not configured for this challenge."}}
        elif len(languages) == 1:
            lang_row = languages[0]
        else:
            return {"success": False, "data": {"message": "Language must be specified."}}

        files = [{
            "name": lang_row.run_file,
            "content": submission
        }]
        if lang_row.data_file:
            files.append({
                "name": lang_row.data_file,
                "content": getContents(lang_row.data_file)
            })

        try:
            r = requests.post(
                RUNNER_URL,
                json={
                    "language": lang_row.language,
                    "version": lang_row.version,
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
            _record_attempt(challenge, submission, payload, lang_row.language, lang_row.version)
            return {"success": True, "data": payload}
        else:
            return {"success": False, "data": {"message": "Non 200 code returned. Talk to an admin."}}


def _record_attempt(challenge, submission, runner_payload, language=None, version=None):
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
        language=language,
        version=version,
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
        rows = (
            CodesubflagChallengeLanguage.query
            .filter_by(challenge_id=challenge.id)
            .order_by(CodesubflagChallengeLanguage.sort_order)
            .all()
        )
        if not rows:
            return {"success": False, "data": {"message": NO_TEMPLATE_MESSAGE}}

        languages = []
        for row in rows:
            template_error = None
            try:
                template = getContents(row.run_file)
            except (FileNotFoundError, OSError, ValueError) as e:
                # Log so admins notice the misconfiguration; surface a flag on
                # the row so the UI can show the standard "Talk to an admin"
                # message instead of an empty editor.
                current_app.logger.warning(
                    "codesubflags: failed to load run_file %r for challenge %s: %s",
                    row.run_file, challenge.id, e,
                )
                template = ""
                template_error = NO_TEMPLATE_MESSAGE
            languages.append({
                "language": row.language,
                "version": row.version,
                "run_file": row.run_file,
                "data_file": row.data_file or "",
                "template": template,
                "template_error": template_error,
                "sort_order": row.sort_order or 0,
            })

        # `message` is preserved for back-compat with anything still reading
        # the old single-template payload — point it at the first language.
        return {
            "success": True,
            "data": {
                "message": languages[0]["template"],
                "history_size": history_size,
                "languages": languages,
            },
        }


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
                        "date": r.date.replace(tzinfo=timezone.utc).isoformat() if r.date else None,
                        "code": r.code,
                        "stdout": r.stdout,
                        "stderr": r.stderr,
                        "language": r.language,
                        "version": r.version,
                    }
                    for r in rows
                ],
            },
        }

@codesubflags_namespace.route("/runtimes")
class Runtimes(Resource):
    """
    Lightweight admin proxy over piston's GET /api/v2/runtimes. Used by the
    challenge-edit form to populate a "what's installed" dropdown.
    """

    @admins_only
    def get(self):
        try:
            r = requests.get(RUNTIMES_URL, timeout=3)
            r.raise_for_status()
        except requests.RequestException:
            return {"success": False, "data": {"message": "Piston not reachable"}}
        try:
            payload = r.json()
        except ValueError:
            return {"success": False, "data": {"message": "Piston returned an invalid response"}}
        runtimes = []
        for entry in payload:
            language = entry.get("language")
            version = entry.get("version")
            if not language or not version:
                continue
            runtimes.append({
                "language": language,
                "version": version,
                "label": f"{language} - {version}",
            })
        runtimes.sort(key=lambda x: (x["language"], _version_sort_key(x["version"])))
        return {"success": True, "data": runtimes}


@codesubflags_namespace.route("/packages")
class Packages(Resource):
    """
    Admin-only thin proxy for piston's package management endpoints. The
    settings page uses these to install/uninstall language runtimes without
    needing the piston CLI.
    """

    @admins_only
    def get(self):
        try:
            r = requests.get(PACKAGES_URL, timeout=5)
            r.raise_for_status()
        except requests.RequestException:
            return {"success": False, "data": {"message": "Piston not reachable"}}
        try:
            payload = r.json()
        except ValueError:
            return {"success": False, "data": {"message": "Piston returned an invalid response"}}
        packages = []
        for entry in payload:
            language = entry.get("language")
            version = entry.get("language_version") or entry.get("version")
            if not language or not version:
                continue
            packages.append({
                "language": language,
                "version": version,
                "installed": bool(entry.get("installed")),
            })
        packages.sort(key=lambda x: (not x["installed"], x["language"], _version_sort_key(x["version"])))
        return {"success": True, "data": packages}

    @admins_only
    def post(self):
        body = request.get_json(silent=True) or {}
        language, version, err = _validated_lang_version(body)
        if err:
            return {"success": False, "data": {"message": err}}
        try:
            # Piston package installs can take 30-90s for some runtimes — let
            # the request stay open long enough rather than failing fast.
            r = requests.post(
                PACKAGES_URL,
                json={"language": language, "version": version},
                timeout=180,
            )
        except requests.RequestException as e:
            return {"success": False, "data": {"message": f"Install failed: {e}"}}
        try:
            payload = r.json()
        except ValueError:
            payload = {"raw": r.text}
        if r.status_code >= 400:
            return {"success": False, "data": payload}
        return {"success": True, "data": payload}

    @admins_only
    def delete(self):
        body = request.get_json(silent=True) or {}
        language, version, err = _validated_lang_version(body)
        if err:
            return {"success": False, "data": {"message": err}}
        try:
            r = requests.delete(
                PACKAGES_URL,
                json={"language": language, "version": version},
                timeout=30,
            )
        except requests.RequestException as e:
            return {"success": False, "data": {"message": f"Uninstall failed: {e}"}}
        try:
            payload = r.json()
        except ValueError:
            payload = {"raw": r.text}
        if r.status_code >= 400:
            return {"success": False, "data": payload}
        return {"success": True, "data": payload}


def _list_dir_entries(fullpath):
    entries = []
    for name in sorted(os.listdir(fullpath)):
        # os.listdir already filters "." and ".." but skip dotfiles to keep
        # the editor focused on real challenge assets.
        if name.startswith("."):
            continue
        child = os.path.join(fullpath, name)
        try:
            st = os.stat(child)
        except OSError:
            continue
        is_dir = os.path.isdir(child)
        entries.append({
            "name": name,
            "type": "dir" if is_dir else "file",
            "size": 0 if is_dir else st.st_size,
            "mtime": int(st.st_mtime),
            "editable": (not is_dir) and _is_text_file(name) and st.st_size <= MAX_EDITABLE_BYTES,
        })
    # Directories first, then files; both alphabetised.
    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
    return entries


@codesubflags_namespace.route("/files")
class ChallengeFilesIndex(Resource):
    """List directory contents and delete individual files/empty dirs."""

    @admins_only
    def get(self):
        rel = request.args.get("path", "") or ""
        try:
            fullpath = _safe_challenge_dir_path(rel)
        except ValueError as e:
            return {"success": False, "data": {"message": str(e)}}, 400
        if not os.path.isdir(fullpath):
            return {"success": False, "data": {"message": "Not a directory"}}, 404
        normalised = _relpath_under_root(fullpath)
        parent = None
        if normalised:
            parent_rel = os.path.dirname(normalised)
            parent = parent_rel  # "" means root
        return {
            "success": True,
            "data": {
                "path": normalised,
                "parent": parent,
                "entries": _list_dir_entries(fullpath),
            },
        }

    @admins_only
    def delete(self):
        rel = request.args.get("path", "") or ""
        try:
            fullpath = _safe_challenge_file_path(rel)
        except ValueError as e:
            return {"success": False, "data": {"message": str(e)}}, 400
        if fullpath == _challenge_files_root():
            return {"success": False, "data": {"message": "Cannot delete the challenge_files root"}}, 400
        if not os.path.exists(fullpath):
            return {"success": False, "data": {"message": "Not found"}}, 404
        try:
            if os.path.isdir(fullpath):
                # Refuse non-empty directories; admin must clear contents first
                # so a stray click can't nuke a folder full of fixtures.
                if os.listdir(fullpath):
                    return {"success": False, "data": {"message": "Directory not empty"}}, 400
                os.rmdir(fullpath)
            else:
                os.remove(fullpath)
        except OSError as e:
            return {"success": False, "data": {"message": f"Delete failed: {e}"}}, 500
        return {"success": True, "data": {}}


@codesubflags_namespace.route("/files/upload")
class ChallengeFilesUpload(Resource):
    @admins_only
    def post(self):
        rel = request.form.get("path", "") or ""
        overwrite = (request.form.get("overwrite") or "").lower() == "true"
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return {"success": False, "data": {"message": "No file uploaded"}}, 400

        # Fast reject before reading the body when the client tells us the size.
        if request.content_length is not None and request.content_length > MAX_UPLOAD_BYTES + 4096:
            return {"success": False, "data": {"message": "File exceeds 10 MB limit"}}, 413

        try:
            target_dir = _safe_challenge_dir_path(rel)
        except ValueError as e:
            return {"success": False, "data": {"message": str(e)}}, 400
        if not os.path.isdir(target_dir):
            return {"success": False, "data": {"message": "Target directory does not exist"}}, 404

        safe_name = secure_filename(upload.filename)
        if not safe_name or not _FILE_NAME_RE.match(safe_name):
            return {"success": False, "data": {"message": "Invalid filename"}}, 400

        target_path = os.path.join(target_dir, safe_name)
        # Re-validate that the joined path stays under root (defence in depth).
        try:
            _safe_challenge_file_path(_relpath_under_root(target_dir) + "/" + safe_name if _relpath_under_root(target_dir) else safe_name)
        except ValueError as e:
            return {"success": False, "data": {"message": str(e)}}, 400

        if os.path.exists(target_path) and not overwrite:
            return {"success": False, "data": {"message": "File exists", "code": "exists"}}, 409
        if os.path.isdir(target_path):
            return {"success": False, "data": {"message": "A directory with this name exists"}}, 400

        # Stream to a temp file in the same dir, count bytes, then atomically
        # replace. Aborts mid-stream if the upload exceeds the limit so we
        # don't waste disk on an oversized file.
        tmp_path = target_path + ".upload-tmp"
        written = 0
        try:
            with open(tmp_path, "wb") as out:
                while True:
                    chunk = upload.stream.read(64 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        out.close()
                        os.remove(tmp_path)
                        return {"success": False, "data": {"message": "File exceeds 10 MB limit"}}, 413
                    out.write(chunk)
            os.replace(tmp_path, target_path)
        except OSError as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            return {"success": False, "data": {"message": f"Upload failed: {e}"}}, 500
        return {"success": True, "data": {"name": safe_name, "size": written}}


@codesubflags_namespace.route("/files/download")
class ChallengeFilesDownload(Resource):
    @admins_only
    def get(self):
        rel = request.args.get("path", "") or ""
        try:
            fullpath = _safe_challenge_file_path(rel)
        except ValueError as e:
            return {"success": False, "data": {"message": str(e)}}, 400
        if fullpath == _challenge_files_root() or not os.path.isfile(fullpath):
            return {"success": False, "data": {"message": "Not a file"}}, 404
        relative = _relpath_under_root(fullpath)
        return send_from_directory(
            _challenge_files_root(),
            relative,
            as_attachment=True,
        )


@codesubflags_namespace.route("/files/mkdir")
class ChallengeFilesMkdir(Resource):
    @admins_only
    def post(self):
        body = request.get_json(silent=True) or {}
        rel = (body.get("path") or "").strip()
        name = (body.get("name") or "").strip()
        if not name or not _FILE_NAME_RE.match(name) or len(name) > 64:
            return {"success": False, "data": {"message": "Invalid folder name"}}, 400
        try:
            parent = _safe_challenge_dir_path(rel)
        except ValueError as e:
            return {"success": False, "data": {"message": str(e)}}, 400
        if not os.path.isdir(parent):
            return {"success": False, "data": {"message": "Parent directory does not exist"}}, 404
        target = os.path.join(parent, name)
        try:
            # Re-validate the joined path against root.
            _safe_challenge_dir_path(_relpath_under_root(target))
        except ValueError as e:
            return {"success": False, "data": {"message": str(e)}}, 400
        if os.path.exists(target):
            return {"success": False, "data": {"message": "Already exists"}}, 409
        try:
            os.mkdir(target)
        except OSError as e:
            return {"success": False, "data": {"message": f"mkdir failed: {e}"}}, 500
        return {"success": True, "data": {"name": name}}


@codesubflags_namespace.route("/files/rename")
class ChallengeFilesRename(Resource):
    @admins_only
    def post(self):
        body = request.get_json(silent=True) or {}
        src_rel = (body.get("from") or "").strip()
        dst_rel = (body.get("to") or "").strip()
        if not src_rel or not dst_rel:
            return {"success": False, "data": {"message": "from and to are required"}}, 400
        try:
            src = _safe_challenge_file_path(src_rel)
            dst = _safe_challenge_file_path(dst_rel)
        except ValueError as e:
            return {"success": False, "data": {"message": str(e)}}, 400
        root = _challenge_files_root()
        if src == root or dst == root:
            return {"success": False, "data": {"message": "Cannot rename the root"}}, 400
        if not os.path.exists(src):
            return {"success": False, "data": {"message": "Source not found"}}, 404
        if os.path.exists(dst):
            return {"success": False, "data": {"message": "Destination exists"}}, 409
        # The destination's basename must match the safe-name regex; anything
        # like control chars or spaces gets rejected here.
        if not _FILE_NAME_RE.match(os.path.basename(dst)):
            return {"success": False, "data": {"message": "Invalid destination name"}}, 400
        # Ensure the destination's parent directory exists.
        if not os.path.isdir(os.path.dirname(dst)):
            return {"success": False, "data": {"message": "Destination directory does not exist"}}, 404
        try:
            os.rename(src, dst)
        except OSError as e:
            return {"success": False, "data": {"message": f"Rename failed: {e}"}}, 500
        return {"success": True, "data": {}}


@codesubflags_namespace.route("/files/contents")
class ChallengeFilesContents(Resource):
    @admins_only
    def get(self):
        rel = request.args.get("path", "") or ""
        try:
            fullpath = _safe_challenge_file_path(rel)
        except ValueError as e:
            return {"success": False, "data": {"message": str(e)}}, 400
        if fullpath == _challenge_files_root() or not os.path.isfile(fullpath):
            return {"success": False, "data": {"message": "Not a file"}}, 404
        if not _is_text_file(fullpath):
            return {"success": False, "data": {"message": "Not a text file"}}, 400
        try:
            size = os.path.getsize(fullpath)
        except OSError as e:
            return {"success": False, "data": {"message": f"Stat failed: {e}"}}, 500
        if size > MAX_EDITABLE_BYTES:
            return {"success": False, "data": {"message": "File too large to edit in browser"}}, 413
        try:
            with open(fullpath, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as e:
            return {"success": False, "data": {"message": f"Read failed: {e}"}}, 500
        return {"success": True, "data": {"content": content, "size": size}}

    @admins_only
    def put(self):
        body = request.get_json(silent=True) or {}
        rel = (body.get("path") or "").strip()
        content = body.get("content")
        if content is None or not isinstance(content, str):
            return {"success": False, "data": {"message": "content must be a string"}}, 400
        if len(content.encode("utf-8")) > MAX_EDITABLE_BYTES:
            return {"success": False, "data": {"message": "Content too large"}}, 413
        try:
            fullpath = _safe_challenge_file_path(rel)
        except ValueError as e:
            return {"success": False, "data": {"message": str(e)}}, 400
        if fullpath == _challenge_files_root():
            return {"success": False, "data": {"message": "Invalid target"}}, 400
        if not _is_text_file(fullpath):
            return {"success": False, "data": {"message": "Not a text file"}}, 400
        if os.path.isdir(fullpath):
            return {"success": False, "data": {"message": "Target is a directory"}}, 400
        if not os.path.isdir(os.path.dirname(fullpath)):
            return {"success": False, "data": {"message": "Parent directory missing"}}, 404
        tmp_path = fullpath + ".edit-tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, fullpath)
        except OSError as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            return {"success": False, "data": {"message": f"Write failed: {e}"}}, 500
        return {"success": True, "data": {"size": os.path.getsize(fullpath)}}


def load(app):
    upgrade()
    app.db.create_all()
    CHALLENGE_CLASSES["codesubflags"] = CodesubflagChallengeType
    register_plugin_assets_directory(app, base_path="/plugins/codesubflags/assets/")
    # Expose the default so admin HTML forms don't have to hardcode it.
    app.jinja_env.globals["CODESUBFLAGS_DEFAULT_HISTORY_SIZE"] = DEFAULT_HISTORY_SIZE

    codesubflags_admin = Blueprint(
        "codesubflags_admin",
        __name__,
        template_folder="templates",
    )

    @codesubflags_admin.route("/admin/codesubflags/")
    @admins_only
    def admin_attempts_listing():
        page = abs(request.args.get("page", 1, type=int))
        challenge_id = request.args.get("challenge_id", type=int)
        user_id = request.args.get("user_id", type=int)

        q = CodesubflagAttempt.query
        if challenge_id:
            q = q.filter_by(challenge_id=challenge_id)
        if user_id:
            q = q.filter_by(user_id=user_id)

        attempts = (
            q.order_by(CodesubflagAttempt.date.desc())
             .paginate(page=page, per_page=50, error_out=False)
        )

        challenges = (
            Challenges.query
            .filter_by(type="codesubflags")
            .order_by(Challenges.name)
            .all()
        )
        users = (
            db.session.query(Users)
            .join(CodesubflagAttempt, CodesubflagAttempt.user_id == Users.id)
            .distinct()
            .order_by(Users.name)
            .all()
        )

        chal_names = {c.id: c.name for c in Challenges.query.all()}
        user_names = {u.id: u.name for u in Users.query.all()}

        args = dict(request.args)
        args.pop("page", None)
        return render_template(
            "codesubflag_attempts.html",
            attempts=attempts,
            challenges=challenges,
            users=users,
            chal_names=chal_names,
            user_names=user_names,
            selected_challenge_id=challenge_id,
            selected_user_id=user_id,
            prev_page=url_for(request.endpoint, page=attempts.prev_num, **args),
            next_page=url_for(request.endpoint, page=attempts.next_num, **args),
        )

    @codesubflags_admin.route("/admin/codesubflags/settings")
    @admins_only
    def admin_settings():
        return render_template("codesubflag_settings.html")

    @codesubflags_admin.route("/admin/codesubflags/files")
    @admins_only
    def admin_files():
        return render_template("codesubflag_files.html")

    @codesubflags_admin.route("/admin/codesubflags/<int:attempt_id>")
    @admins_only
    def admin_attempt_detail(attempt_id):
        attempt = CodesubflagAttempt.query.filter_by(id=attempt_id).first()
        if attempt is None:
            abort(404)

        challenge = Challenges.query.filter_by(id=attempt.challenge_id).first()
        user = Users.query.filter_by(id=attempt.user_id).first()

        # Preserve listing filters/page when sending the user back.
        back_args = {
            k: v for k, v in request.args.items()
            if k in ("page", "challenge_id", "user_id")
        }
        back_url = url_for(
            "codesubflags_admin.admin_attempts_listing", **back_args
        )

        return render_template(
            "codesubflag_attempt_detail.html",
            attempt=attempt,
            challenge_name=challenge.name if challenge else attempt.challenge_id,
            user_name=user.name if user else attempt.user_id,
            back_url=back_url,
        )

    app.register_blueprint(codesubflags_admin)
    register_admin_plugin_script("/plugins/codesubflags/assets/admin_nav.js")

    # creates all necessairy endpoints
    CTFd_API_v1.add_namespace(codesubflags_namespace, '/codesubflags')
