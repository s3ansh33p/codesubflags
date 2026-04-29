// Injects "Code Submissions" and "Challenge Files" links into the existing
// admin Submissions dropdown. Kept as a pure DOM patch so the plugin stays
// self-contained — no edits to CTFd's core admin theme required.
(function () {
    function appendLink(menu, root, id, href, text) {
        if (document.getElementById(id)) return;
        var link = document.createElement("a");
        link.id = id;
        link.className = "dropdown-item";
        link.href = root + href;
        link.textContent = text;
        menu.appendChild(link);
    }

    function injectLinks() {
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
        appendLink(menu, root, "codesubflags-nav-link", "/admin/codesubflags/", "Code Submissions");
        appendLink(menu, root, "codesubflags-files-nav-link", "/admin/codesubflags/files", "Challenge Files");
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", injectLinks);
    } else {
        injectLinks();
    }
})();
