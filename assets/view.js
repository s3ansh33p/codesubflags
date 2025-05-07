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
    console.log(challenge_id)

    CTFd.fetch(`/api/v1/codesubflags/challenges/${challenge_id}/view`, {
        method: "GET"
    })
    .then((response) => response.json())
    .then((data) => {
        let order_array = [];
        Object.keys(data).forEach(key => {
            order_array.push(key)
        });
        order_array.sort(function(a,b){
            return data[a]["order"] - data[b]["order"];
        });

        // insert codesubflags headline if at least one codesubflag exists
        if (order_array.length > 0) {
            CTFd.lib.$("#codesubflags").append("<h5>Flags:</h5>");
        }
        

        // goes through the list of codesubflag ids
        for (let i = 0; i < order_array.length; i++) {
            // temp codesubflag variables (id, desc, whether the codesubflag is solved by the current team)
            let id = order_array[i];
            let desc = data[id].desc;
            let placeholder = data[id].placeholder;
            let points = data[id].points;
            let codesubflag_solved_by_me = data[id].solved;

            if (!placeholder) {
                placeholder = "Submit subflag for extra awards.";
            }

            // if the codesubflag is already soved -> insert a disabled form field with lightgreen background and an delete button 
            if (codesubflag_solved_by_me) {
                var keys = `<form id="codesubflag_form` + id + `">
                        <p class="form-text">
                            ` + desc + `
                            | Points:  <b>+` + points + `</b>
                        </p> 
                        <div class="row" style="margin-bottom: 10px;">
                            <div class="col-md-9">
                                <input type="text" class="form-control chal-codesubflag_key" name="answer" placeholder="Subflag Solved!" style="background-color:#f5fff1;" disabled>
                            </div>
                            
                        </div>
                    </form>
                    <div id="codesubflag_hints_` + id + `"> </div>`;
            // if the codesubflag is not yet solved -> insert a formfield with a submit button
            } else {
                var keys = `<form id="codesubflag_form` + id + `" onsubmit="submit_codesubflag(event, ${id})">
                    <p class="form-text">
                        ` + desc + `
                        | Points:  <b>+` + points + `</b>
                    </p>
                    <div class="row">
                        <div class="col-md-9 form-group">
                            <input type="text" class="form-control chal-codesubflag_key" name="answer" placeholder=" ` + placeholder + `" required>
                        </div>
                        <div class="col-md-3 form-group" id=submit style="margin-top: 6px;">
                            <input type="submit" value="Submit" class="btn btn-md btn-outline-secondary float-right">
                        </div>
                    </div>
                </form>
                <div id="codesubflag_hints_` + id + `"> </div>`;
          }      
          CTFd.lib.$("#codesubflags").append(keys);      
          
          // creates an array of hint ids and sorts them according to their order
          let hintdata = [];
          Object.keys(data[id].hints).forEach(key => {
              hintdata.push(key);
          });
          hintdata.sort(function(a,b){
              return data[id].hints[a].order - data[id].hints[b].order;
          });
          
          // calls a function to move the hints to the according position
          move_codesubflag_hints(id, hintdata);
        }
        // include headline for main flag at the end
        if (order_array.length > 0) {
            CTFd.lib.$("#codesubflags").append("<h5>Main Flag:</h5>");
        }
    });
}

function get_code_template() {
    // post to /api/v1/codesubflags/get/${challenge_id}
    const challenge_id = parseInt(CTFd.lib.$('#challenge-id').val())

    CTFd.fetch(`/api/v1/codesubflags/get/${challenge_id}`, {
      method: "GET"
    })
    .then((response) => response.json())
    .then((data) => {
        data = data.data.message;
        const editor = CodeMirror.fromTextArea(document.getElementById("coderunner"), {
            lineNumbers: true,
            mode: "python",
            indentUnit: 4,
            indentWithTabs: true,
            readOnly: false,
            theme: "dracula",
        });
        editor.setSize("100%", "500px");
        editor.save();
        editor.setValue(data);
        setTimeout(() => {
            editor.refresh();
            editor.focus();
            // set cursor to end
            editor.setCursor(editor.lineCount(), 0);
        }, 200);
        window.editor = editor;
    });
}

function run_code() {
    // button with post request to /api/codesubflags/run
    // calls the api endpoint to attach a hint to a codesubflag
    const challenge_id = parseInt(CTFd.lib.$('#challenge-id').val())
    // const submission = CTFd.lib.$('#coderunner').val()
    // get submission from editor
    const editor = window.editor;
    editor.save();
    const submission = editor.getValue();

    const body = {
        challenge_id: challenge_id,
        submission: submission
    }

    CTFd.fetch(`/api/v1/codesubflags/run/${challenge_id}`, {
      method: "POST",
      body: JSON.stringify(body)
    })
    .then((response) => response.json())
    .then((data) => {
        data = data.data.run;
        CTFd.lib.$('#coderunner-output').html(data.output)
        CTFd.lib.$("#coderunner-errors").html(data.stderr)
        if (data.signal == "SIGKILL" && data.stderr == "" && data.output == "") {
            CTFd.lib.$("#coderunner-errors").html("Your code may have timed out. Please try again. (max execution time of 5 seconds)")
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
