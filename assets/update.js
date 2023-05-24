// creates a array to store the ids of all used hints
var used_hints = [];

CTFd.plugin.run((_CTFd) => {
    const $ = _CTFd.lib.$
    const md = _CTFd.lib.markdown()
    $(document).ready(function() {
        // run insert_codesubflags when the page is loaded
        insert_codesubflags();
    });
});

// inserts the codesubflags
function insert_codesubflags(){
    // fetches the information needed from the backend
    $.get(`/api/v1/codesubflags/challenges/${CHALLENGE_ID}/update`).done( function(data) {
        // pushed the id of all codesubflags into an array
        let order_array = [];
        Object.keys(data).forEach(key => {
            order_array.push(key);
        });
        // orders the ids based on the order of the codesubflags
        order_array.sort(function(a,b){return data[a]["order"] - data[b]["order"]});
        let len = order_array.length;
        // for all codesubflags
        for (let i = 0; i < len; i++) {
            // temp save for needed variables
            let id = order_array[i];
            let name = data[id].name;
            let desc = data[id].desc;
            let placeholder = data[id].placeholder;
            let key = data[id].key;
            let order = data[id].order;
            let points = data[id].points;


            // creates html code to append a hint to the specified codesubflag section
            // displays: codesubflag id, codesubflag solution, codesubflag order, button to update the codesubflag, button to delete the codesubflag, button to add a hint to the codesubflag
            let keys = `<div id="codesubflag` + id + `">
                            <form id="codesubflag_update_form" onsubmit="update_codesubflag(${id}, event)">
                                <label> 
                                    Subflag ID: ` + id + `<br>
                                </label>
                                <small class="form-text text-muted">
                                    The Subflag Name:
                                </small>
                                <input type="text" class="form-control chal" name="codesubflag_name" value="` + name + `" required>
                                <small class="form-text text-muted">
                                    The Subflag Description:
                                </small>
                                <input type="text" class="form-control chal" name="codesubflag_desc" value="` + desc + `" required>
                                <small class="form-text text-muted">
                                    The Subflag Key:
                                </small>
                                <input type="text" class="form-control chal" name="codesubflag_placeholder" value="` + placeholder + `" required>
                                <small class="form-text text-muted">
                                    The Subflag Placeholder:
                                </small>
                                <input type="text" class="form-control chal" name="codesubflag_key" value="` + key + `" required>
                                <small class="form-text text-muted">
                                    The Subflag Order:
                                </small>
                                <input type="text" class="form-control chal" name="codesubflag_order" value="` + order + `" step="1" required>
                                <small class="form-text text-muted">
                                    The Subflag Points:
                                </small>
                                <input type="text" class="form-control chal" name="codesubflag_points" value="` + points + `" step="1" required>

                                <div class="row" style="margin-top: 12px; margin-bottom: 15px;">
                                    <div class="col-md-6" style="text-align:left;">
                                        <button class="btn btn-theme btn-outlined" id="add-new-codesubflag" type="submit">
                                            Update Subflag
                                        </button>
                                    </div>
                                    <div class="col-md-6" style="text-align:right;" >
                                        <button type="button" class="btn btn-outline-danger" data-toggle="tooltip" title="delete Subflag" id="challenges-delete-button" data-original-title="Delete Subflag" onclick="delete_codesubflag(` + id + `)">
                                            <i class="btn-fa fas fa-trash-alt"></i>
                                        </button>
                                    </div>
                                </div>
                            </form>
                            <div id="codesubflaghints` + id + `">
                                <label> Attached Hints: </label>
                            </div>
                            <div style="text-align:center;">
                                <button class="btn btn-theme btn-outlined" id="add_hint` + id + `" onclick="add_hint(` + id + `)">
                                    Add new Hint
                                </button>
                            </div>
                            <hr style="border-top: 1px solid grey;">
                        </div>`;
            $("#codesubflags").append(keys);

            // calls funtion to add hint to the codesubflag
            insert_codesubflag_hints(id, data[id]["hints"])
        }
    });
}

// inserts the hints for a specified codesubflag
// inputs: codesubflag id; array containing objects composed of hint_id: (order, content)
function insert_codesubflag_hints(codesubflag_id, codesubflag_hintdata){
        // orders the array of objects according to the order of the hints
        let order_array = [];
        Object.keys(codesubflag_hintdata).forEach(key => {
            order_array.push(key);
        });
        order_array.sort(function(a,b){return codesubflag_hintdata[a]["order"] - codesubflag_hintdata[b]["order"]});
        
        // inserts a div placeholder for the hint beneath the codesubflag
        for (let i = 0; i< order_array.length; i++){
            let hint_id = order_array[i];
            let insert = `<div id = codesubflag_hint_` + hint_id + `> </div>`
            $("#codesubflaghints" + codesubflag_id).append(insert);
        }

        // gets a list of all hints including the content of the hint 
        $.get("/api/v1/challenges/" + CHALLENGE_ID + "/hints").done(function(data) {
            let hintdata = data.data;
            // for all hints to the 
            for (let i = 0; i < order_array.length; i++){
                // create temp variables for needed data
                let hint_id = order_array[i];
                let hint_order = codesubflag_hintdata[hint_id].order;
                let hint_content = hintdata.filter(hint => hint.id == hint_id)[0].content;
                
                // pushes the id of the hint to the array of used hints
                used_hints.push(parseInt(hint_id));

                // creates html code to append a hint to the specified codesubflag section
                // displays: hint content, hint id, hint order, detach button
                let insert =   `<small class="form-text text-muted">
                                    Hint Content: 
                                </small>
                                <p> ` + hint_content + ` </p>
                                <div class="row">
                                    <div class="col-md-4" style="text-align:left;">
                                        <small class="form-text text-muted">
                                            Hint ID: 
                                        </small>
                                        <p> ` + hint_id + ` </p>
                                    </div>
                                    <div class="col-md-4" style="text-align:center;">
                                        <small class="form-text text-muted">
                                            Hint Order: 
                                        </small>
                                        <p> ` + String(hint_order) + ` </p>
                                    </div>
                                    <div class="col-md-4" style="text-align:right;">
                                        <small class="form-text text-muted">
                                            Detach Hint:
                                        </small>
                                        <button type="button" class="btn btn-outline-danger" data-toggle="tooltip" title="delete Hint" id="hint_deattach_button" data-original-title="Deattach Hint" onclick="remove_hint(` + hint_id + `)">
                                            <i class="btn-fa fas fa-trash-alt"></i>
                                        </button>
                                    </div>
                                </div>
                                <hr>`;
                $("#codesubflag_hint_" + hint_id).append(insert);
            }
        });
}

// function to submit the changes made to a codesubflag
// inputs: event from the update form containing: codesubflag id, desc, key, order
function update_codesubflag(codesubflag_id, event){
    event.preventDefault();
    let params = $(event.target).serializeJSON(true);

    // calls api endpoint to update the codesubflag with the form input fields
    CTFd.fetch(`/api/v1/codesubflags/${codesubflag_id}`, {
        method: "PATCH",
        body: JSON.stringify(params)
    })
        .then((response) => response.json())
        .then((data) => {
            if (data.success) {
                location.reload();
            }
            else {
                console.log(data);
                alert("something went wrong!");
            }
        });
}

// function to delete a codesubflag
// input: codesubflag id
function delete_codesubflag(codesubflag_id){
    // calls api endpoint to delete a codesubflag with the codesubflag id
    CTFd.fetch(`/api/v1/codesubflags/${codesubflag_id}`, {
        method: "DELETE",
    })
        .then((response) => response.json())
        .then((data) => {
            if (data.success) {
                location.reload();
            }
            else {
                console.log(data);
                alert("something went wrong!");
            }
        });
}

//function to add a codesubflag
function add_codesubflag() {
    // defines the parameters to create a new challenge with
    let params = {
        challenge_id: window.CHALLENGE_ID, 
        codesubflag_name: "CHANGE ME",
        codesubflag_desc: "CHANGE ME",
        codesubflag_placeholder: "CHANGE ME",
        codesubflag_key: "CHANGE ME",
        codesubflag_order: 1,
        codesubflag_points: 1
    }

    // calls api endpoint to create a new challenge with the desc and key "CHANGE_ME" and order 0 and then reloads the page
    CTFd.fetch("/api/v1/codesubflags", {
        method: "POST",
        body: JSON.stringify(params)
    })
        .then((response) => response.json())
        .then((data) => {
            if (data.success) {
                location.reload();
            }
            else {
                console.log(data);
                alert("something went wrong!");
            }
        });
}

// adds fields to attach a new hint to a specific codesubflag
// inputs: codesubflag id
function add_hint(codesubflag_id) {
    let element = document.getElementById("add_hint" + codesubflag_id);
    element.parentNode.removeChild(element);

    // allows the player to select a hint from the available hints and define the order in which the hint will be displayed in relation to other hints
    $.get("/api/v1/challenges/" + CHALLENGE_ID + "/hints").done( function(data){
        let insert= `<form id = "add_hint` + codesubflag_id + `" onsubmit="attach_hint(event)">
                        <small class="form-text text-muted">
                            Choose a Hint:
                        </small>
                        <select id="codesubflag_hint_select_` + codesubflag_id + `" name="hint_id" form="add_hint`+ codesubflag_id + `" class="form-control" required>
                            <option value="" disabled selected>Select One Hint from the list</option>
                        </select>
                        
                        <small class="form-text text-muted">
                            Enter a Hint Order
                        </small>
                        <div class="row">
                            <div class="col-md-9" style="text-align:left;">
                                <input type="text" class="form-control chal" name="hint_order" step="1" placeholder="Enter Integer Number" required>
                            </div>
                            <div class="col-md-3" style="text-align:right;">
                                <button class="btn btn-theme btn-outlined" type="submit">
                                    Add
                                </button>
                            </div>
                        </div>
                        <input type="text" name="codesubflag_id" value="` + codesubflag_id + `" hidden>
                    </form>`;  
        $("#codesubflaghints" + codesubflag_id).append(insert);

        // populates the hint selector with hints that are not yet already used in other codesubflags 
        Object.keys(data.data).forEach(key => {
            if ( used_hints.includes(data.data[key].id) == false ){
                $("#codesubflag_hint_select_" + codesubflag_id).append($("<option />").val(data.data[key].id).text(data.data[key].content));
            }
        });
    });
}

// attaches a hint to a codesubflag
// inputs: html form event containing the hint id, codesubflag id and hint order
function attach_hint(event) {
    // prevents to submit button to jump to the specified page
    event.preventDefault();
    const params = $(event.target).serializeJSON(true); 

    // calls the api endpoint to attach a hint to a codesubflag
    CTFd.fetch(`/api/v1/codesubflags/hints/${params.hint_id}`, {
        method: "POST",
        body: JSON.stringify(params)
    })
        .then((response) => response.json())
        .then((data) => {
            if (data.success) {
                location.reload();
            }
            else {
                console.log(data);
                alert("something went wrong!");
            }
        });
}

// removes a hint from a codesubflag
// inputs: hint id
function remove_hint(hint_id) {

    // calls the api endpoint to attach a hint to a codesubflag
    CTFd.fetch(`/api/v1/codesubflags/hints/${hint_id}`, {
        method: "DELETE",
    })
        .then((response) => response.json())
        .then((data) => {
            if (data.success) {
                location.reload();
            }
            else {
                console.log(data);
                alert("something went wrong!");
            }
        });
}