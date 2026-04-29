CTFd.plugin.run((_CTFd) => {
    const $ = _CTFd.lib.$
    const md = _CTFd.lib.markdown()
})

// Adds counter for the number of the subflags
var count = 0;

// Adds input fields for Description, flag, order when the button "Add Subflags" is clicked
// Uses count to differentiate betweet subflags
$("#add-new-subflag").click(function () {
    var key = `<div class="form-group">
                  <label>Subflag</label>
                  <input type="text" class="form-control" name="subflag_name[` + count + `]" placeholder="Enter Subflag Name">
                  <input type="text" class="form-control" name="subflag_desc[` + count + `]" placeholder="Enter Subflag Description">
                  <input type="text" class="form-control" name="subflag_placeholder[` + count + `]" placeholder="Enter Subflag Placeholder">
                  <input type="text" class="form-control" name="subflag_solution[` + count + `]" placeholder="Enter Subflag Solution">
                  <input type="number" class="form-control" name="subflag_order[` + count + `]" placeholder="Enter Subflag Order" step="1">
                  <input type="number" class="form-control" name="subflag_points[` + count + `]" placeholder="Enter Subflag Points" step="1">

               </div>`
    $('#subflag_list').append(key);
    count += 1;
});

// Pull the shared languages-editor helper in once the form is on the page,
// then bootstrap the repeater with a single python row so a fresh challenge
// is immediately runnable on a default piston install.
function loadCodesubflagLanguagesEditor(then) {
    if (typeof window.setupCodesubflagLanguagesEditor === "function") {
        then();
        return;
    }
    var s = document.createElement("script");
    s.src = "/plugins/codesubflags/assets/languages_editor.js";
    s.onload = then;
    document.head.appendChild(s);
}

$(document).ready(function () {
    $('[data-toggle="tooltip"]').tooltip();
    loadCodesubflagLanguagesEditor(function () {
        window.setupCodesubflagLanguagesEditor({
            prefill: [{ language: "python", version: "3.10.0", run_file: "main.py", data_file: "" }]
        });
    });
});
