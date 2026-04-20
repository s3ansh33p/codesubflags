// Injects a "Code Submissions" link into the existing admin Submissions
// dropdown. Kept as a pure DOM patch so the plugin stays self-contained —
// no edits to CTFd's core admin theme required.
(function () {
    function injectLink() {
        if (document.getElementById("codesubflags-nav-link")) return;

        // Find the "Submissions" dropdown toggle in the admin navbar.
        var toggles = document.querySelectorAll(
            ".navbar .nav-item.dropdown > a.dropdown-toggle"
        );
        var menu = null;
        for (var i = 0; i < toggles.length; i++) {
            if ((toggles[i].textContent || "").trim() === "Submissions") {
                menu = toggles[i].parentNode.querySelector(".dropdown-menu");
                break;
            }
        }
        if (!menu) return;

        var root = (window.init && window.init.urlRoot) || "";
        var link = document.createElement("a");
        link.id = "codesubflags-nav-link";
        link.className = "dropdown-item";
        link.href = root + "/admin/codesubflags/";
        link.textContent = "Code Submissions";
        menu.appendChild(link);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", injectLink);
    } else {
        injectLink();
    }
})();
