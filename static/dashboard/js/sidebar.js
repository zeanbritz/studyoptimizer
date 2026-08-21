document.addEventListener(
    "DOMContentLoaded",
    function () {

        const sidebar =
            document.getElementById(
                "sidebar"
            );

        const menuButton =
            document.getElementById(
                "menuButton"
            );


        if (
            !sidebar
            || !menuButton
        ) {
            return;
        }


        menuButton.addEventListener(
            "click",
            function () {

                sidebar.classList.toggle(
                    "closed"
                );

            }
        );

    }
);