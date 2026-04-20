CTFd._internal.challenge.data = undefined;

CTFd._internal.challenge.preRender = function() {};

CTFd._internal.challenge.postRender = async function() {
    await new Promise(resolve => setTimeout(resolve, 1));
    assign_hint_ids();
    // insert the codesubflags into the view
    insert_codesubflags();

    // Ensure CodeMirror is loaded before calling get_code_template
    await ensureCodeMirrorLoaded();
    get_code_template();
}

// Utility function to dynamically load a script
function loadScript(src, integrity, crossorigin) {
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.integrity = integrity;
        script.crossOrigin = crossorigin;
        script.referrerPolicy = "no-referrer";
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
    });
}

// Ensure CodeMirror is loaded before calling get_code_template
function ensureCodeMirrorLoaded() {
    const codemirrorSrc = "https://cdnjs.cloudflare.com/ajax/libs/codemirror/6.65.7/codemirror.min.js";
    const codemirrorIntegrity = "sha512-8RnEqURPUc5aqFEN04aQEiPlSAdE0jlFS/9iGgUyNtwFnSKCXhmB6ZTNl7LnDtDWKabJIASzXrzD0K+LYexU9g==";
    const pythonModeSrc = "https://cdnjs.cloudflare.com/ajax/libs/codemirror/6.65.7/mode/python/python.min.js";
    const pythonModeIntegrity = "sha512-2M0GdbU5OxkGYMhakED69bw0c1pW3Nb0PeF3+9d+SnwN1ryPx3wiDdNqK3gSM7KAU/pEV+2tFJFbMKjKAahOkQ==";

    return loadScript(codemirrorSrc, codemirrorIntegrity, "anonymous")
        .then(() => loadScript(pythonModeSrc, pythonModeIntegrity, "anonymous"))
        .catch((error) => {
            console.error("Failed to load CodeMirror scripts:", error);
        });
}

// assigns ids to the original html hint element
function assign_hint_ids(){
    // identifies the hint div by class
    let hints = document.getElementsByClassName("col-md-12 hint-button-wrapper text-center mb-3");
    let len = hints.length
    for (let i = 0; i < len; i++) {
        // gets the hint id from the custom "data-hint-id" attribute
        let hint_id = "hint_" + hints[i].children[0].getAttribute("data-hint-id")
        // sets the attribute id to the hint id
        hints[i].setAttribute('id', hint_id);
    }
}

// inserts the codesubflags into the view
function insert_codesubflags(){
    // gets the challenge id from the CTFd lib
    let challenge_id = parseInt(CTFd.lib.$('#challenge-id').val())

    CTFd.fetch(`/api/v1/codesubflags/challenges/${challenge_id}/view`, {
        method: "GET"
    })
    .then((response) => response.json())
    .then((data) => {
        const order_array = Object.keys(data).sort((a, b) => data[a].order - data[b].order);

        // insert codesubflags headline if at least one codesubflag exists
        if (order_array.length > 0) {
            CTFd.lib.$("#codesubflags").append("<h5>Flags:</h5>");
        }

        for (const id of order_array) {
            const cs = data[id];
            CTFd.lib.$("#codesubflags").append(render_codesubflag_form(id, cs));

            // hints sorted by order, then re-parented under this subflag
            const hintdata = Object.keys(cs.hints).sort(
                (a, b) => cs.hints[a].order - cs.hints[b].order
            );
            move_codesubflag_hints(id, hintdata);
        }
        // include headline for main flag at the end
        if (order_array.length > 0) {
            CTFd.lib.$("#codesubflags").append("<h5>Main Flag:</h5>");
        }
    });
}

// Build the subflag form. Solved and unsolved branches share the same
// shell — they differ only in the input (disabled vs. writable) and the
// submit button (present only when unsolved).
function render_codesubflag_form(id, cs) {
    const desc = cs.desc;
    const points = cs.points;
    const placeholder = cs.placeholder || "Submit subflag for extra awards.";
    const solved = cs.solved;

    const input = solved
        ? `<input type="text" class="form-control chal-codesubflag_key" name="answer" placeholder="Subflag Solved!" style="background-color:#f5fff1;" disabled>`
        : `<input type="text" class="form-control chal-codesubflag_key" name="answer" placeholder=" ${placeholder}" required>`;

    const submitCol = solved
        ? ``
        : `<div class="col-md-3 form-group" id=submit style="margin-top: 6px;">
               <input type="submit" value="Submit" class="btn btn-md btn-outline-secondary float-right">
           </div>`;

    const formAttrs = solved ? `` : ` onsubmit="submit_codesubflag(event, ${id})"`;

    return `<form id="codesubflag_form${id}"${formAttrs}>
                <p class="form-text">${desc} | Points: <b>+${points}</b></p>
                <div class="row" style="margin-bottom: 10px;">
                    <div class="col-md-9 form-group">${input}</div>
                    ${submitCol}
                </div>
            </form>
            <div id="codesubflag_hints_${id}"> </div>`;
}

// Namespaced state bag so we aren't sprinkling window.codesubflags_* globals.
// history_size semantics match the server-side contract in __init__.py:
//   HISTORY_DISABLED (-1): no server retention, dropdown stays hidden
//   0:                     unlimited (server still caps via MAX_HISTORY_CAP)
//   N > 0:                 keep last N runs per user per challenge
const HISTORY_DISABLED = -1;
const DEFAULT_HISTORY_SIZE_FALLBACK = 10;
window.codesubflags = window.codesubflags || {
    editor: null,
    template: null,
    challenge_id: null,
    history_size: DEFAULT_HISTORY_SIZE_FALLBACK,
    attempts: {},
    // Monotonic counter so older in-flight history fetches can't clobber newer ones.
    history_fetch_seq: 0,
};

// localStorage key for a user's in-progress draft for a given challenge.
function draft_key(challenge_id) {
    return `codesubflags_draft_${challenge_id}`;
}

function save_draft(id, code) { localStorage.setItem(draft_key(id), code); }
function clear_draft(id)      { localStorage.removeItem(draft_key(id)); }
// Guarded: runs on the editor's init path, so a throw here would prevent the
// editor from rendering at all (e.g. Safari private mode, blocked storage).
function load_draft(id) { try { return localStorage.getItem(draft_key(id)); } catch (e) { return null; } }

function debounce(fn, ms) {
    let t = null;
    return function (...args) {
        if (t) clearTimeout(t);
        t = setTimeout(() => fn.apply(this, args), ms);
    };
}

function get_code_template() {
    const challenge_id = parseInt(CTFd.lib.$('#challenge-id').val());

    CTFd.fetch(`/api/v1/codesubflags/get/${challenge_id}`, {
      method: "GET"
    })
    .then((response) => response.json())
    .then((data) => {
        if (!data || !data.success) {
            console.error("codesubflags: template fetch unsuccessful", data);
            return;
        }
        const template = data.data.message;
        const history_size = data.data?.history_size ?? DEFAULT_HISTORY_SIZE_FALLBACK;

        // Remember the clean starting template so Reset works without a refetch.
        window.codesubflags.template = template;
        window.codesubflags.challenge_id = challenge_id;
        window.codesubflags.history_size = history_size;

        const editor = CodeMirror.fromTextArea(document.getElementById("coderunner"), {
            lineNumbers: true,
            mode: "python",
            indentUnit: 4,
            // Tabs -> spaces to avoid mixed indentation in submitted code.
            indentWithTabs: false,
            readOnly: false,
            theme: "dracula",
            extraKeys: {
                Tab: function(cm) {
                    const spaces = Array(cm.getOption("indentUnit") + 1).join(" ");
                    cm.replaceSelection(spaces);
                },
                "Shift-Tab": "indentLess"
            }
        });
        editor.setSize("100%", "500px");

        // Prefer a locally saved draft so accidental navigation doesn't lose work.
        const draft = load_draft(challenge_id);
        const initial = (draft !== null && draft !== "") ? draft : template;
        editor.setValue(initial);

        // Debounced autosave so every keystroke doesn't hit localStorage.
        const persist = debounce(() => {
            editor.save();
            save_draft(challenge_id, editor.getValue());
        }, 500);
        editor.on("change", persist);

        setTimeout(() => {
            editor.refresh();
            editor.focus();
            editor.setCursor(editor.lineCount(), 0);
        }, 200);
        window.codesubflags.editor = editor;
        // Kept for backwards-compat — some hand-pasted console snippets still poke window.editor.
        window.editor = editor;

        // Server-side history is optional — only render the UI when the admin enabled it.
        if (history_size !== HISTORY_DISABLED) {
            refresh_history_dropdown();
        }
    })
    .catch((err) => {
        console.error("codesubflags: template fetch failed", err);
    });
}

function refresh_history_dropdown() {
    const state = window.codesubflags;
    const challenge_id = state.challenge_id;
    if (challenge_id === null || typeof challenge_id === "undefined") return;

    // Tag this request so stale responses don't clobber a newer dropdown state.
    const seq = ++state.history_fetch_seq;

    CTFd.fetch(`/api/v1/codesubflags/attempts/${challenge_id}`, {
        method: "GET"
    })
    .then((response) => response.json())
    .then((data) => {
        if (seq !== state.history_fetch_seq) return; // superseded by a newer fetch
        if (!data.success) return;
        const attempts = data.data?.attempts ?? [];
        const row = document.getElementById("coderunner-history-row");
        const select = document.getElementById("coderunner-history");
        if (!row || !select) return;

        // Cache so restore doesn't need another round-trip.
        state.attempts = {};
        attempts.forEach((a) => { state.attempts[a.id] = a; });

        select.innerHTML = '<option value="">Restore a previous run…</option>';
        attempts.forEach((a) => {
            const opt = document.createElement("option");
            opt.value = a.id;
            const when = a.date ? new Date(a.date).toLocaleString() : "";
            const preview = (a.code || "").split("\n")[0].slice(0, 40);
            opt.textContent = `${when} — ${preview}`;
            select.appendChild(opt);
        });

        row.style.display = attempts.length > 0 ? "" : "none";
    });
}

function restore_selected_attempt() {
    const state = window.codesubflags;
    const select = document.getElementById("coderunner-history");
    if (!select || !select.value) return;
    const attempt = state.attempts[select.value];
    if (!attempt || !state.editor) return;
    if (!confirm("Replace the current editor contents with this saved run?")) return;

    state.editor.setValue(attempt.code || "");
    state.editor.save();
    save_draft(state.challenge_id, state.editor.getValue());
}

function reset_code_to_default() {
    const state = window.codesubflags;
    // Guard against the template fetch having failed — without this, Reset
    // would blank the editor instead of no-oping.
    if (!state.editor || typeof state.template !== "string") return;
    if (!confirm("Reset the editor to the original starting code? Your current draft will be lost.")) return;

    clear_draft(state.challenge_id);
    state.editor.setValue(state.template);
    state.editor.save();
    state.editor.focus();
    state.editor.setCursor(state.editor.lineCount(), 0);
}

function run_code() {
    const state = window.codesubflags;
    const challenge_id = parseInt(CTFd.lib.$('#challenge-id').val());
    const editor = state.editor;
    if (!editor) return;
    editor.save();
    const submission = editor.getValue();

    const body = {
        challenge_id: challenge_id,
        submission: submission
    };

    // Persist the current buffer before firing the run — belt-and-braces in case
    // of a network error or the user navigating away while the request is in flight.
    save_draft(challenge_id, submission);

    CTFd.fetch(`/api/v1/codesubflags/run/${challenge_id}`, {
      method: "POST",
      body: JSON.stringify(body)
    })
    .then((response) => response.json())
    .then((data) => {
        const run = data.data.run;
        CTFd.lib.$('#coderunner-output').html(run.output);
        CTFd.lib.$("#coderunner-errors").html(run.stderr);
        if (run.signal == "SIGKILL" && run.stderr == "" && run.output == "") {
            CTFd.lib.$("#coderunner-errors").html("Your code may have timed out. Please try again. (max execution time of 5 seconds)");
        }
        if (state.history_size !== HISTORY_DISABLED) {
            refresh_history_dropdown();
        }
    });
}

// moves the original hint html element to the right position beneath the codesubflag
// input: codesubflag id, hintdata: array of hint ids
function move_codesubflag_hints(codesubflag_id, hintdata) {
    for (let i = 0; i < hintdata.length; i++) {
        // move the element
        document.getElementById("codesubflag_hints_" + codesubflag_id).appendChild( document.getElementById("hint_" + hintdata[i]) );
    }
}

// function to submit a codesubflag solution (gets called when the player presses submit)
// input: form event containing: codesubflag id, answer
function submit_codesubflag(event, codesubflag_id) {
    event.preventDefault();
    const params = Object.fromEntries(new FormData(event.target).entries());

    // calls the api endpoint to attach a hint to a codesubflag
    CTFd.fetch(`/api/v1/codesubflags/solve/${codesubflag_id}`, {
      method: "POST",
      body: JSON.stringify(params)
  })
      .then((response) => response.json())
      .then((data) => {
          if (data.data.solved) {
              location.reload();
          }
          else {
              console.log(data);
              alert("wrong answer!");
          }
      });
}

// function to delete a correct codesubflag answer
// input: codesubflag id
function delete_codesubflag_submission(codesubflag_id){
    // calls the api endpoint to post a solve attempt to a codesubflag
    CTFd.fetch(`/api/v1/codesubflags/solve/${codesubflag_id}`, {
        method: "DELETE"
    })
        .then((response) => response.json())
        .then((data) => {
            if (data.success) {
                location.reload();
            }
            else {
                console.log(data);
                alert("wrong answer!");
            }
        });
}

CTFd._internal.challenge.submit = function (preview) {
    var challenge_id = parseInt(CTFd.lib.$('#challenge-id').val())
    var submission = CTFd.lib.$('#challenge-input').val()

    var body = {
        'challenge_id': challenge_id,
        'submission': submission,
    }
    var params = {}
    if (preview) {
        params['preview'] = true
    }

    return CTFd.api.post_challenge_attempt(params, body).then(function (response) {
        if (response.status === 429) {
            // User was ratelimited but process response
            return response
        }
        if (response.status === 403) {
            // User is not logged in or CTF is paused.
            return response
        }
        return response
    })
};
