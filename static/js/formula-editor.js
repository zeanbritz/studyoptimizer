let formulaElements = [];

const formulaCanvas = document.getElementById("formula-canvas");


function addElement(type, value = "") {

    const element = {
        id: crypto.randomUUID(),
        type: type,
        value: value,
        meaning: ""
    };

    formulaElements.push(element);

    renderFormula();
}


function renderFormula() {

    formulaCanvas.innerHTML = "";

    formulaElements.forEach((element, index) => {

        const box = document.createElement("div");

        box.className = "formula-element";

        box.dataset.id = element.id;

        box.draggable = true;

        box.textContent = element.value || "?";


        // Edit
        box.addEventListener("click", () => {

            showEditor(element);

        });


        // Start dragging
        box.addEventListener("dragstart", (event) => {

            event.dataTransfer.effectAllowed = "move";

            event.dataTransfer.setData(
                "text/plain",
                element.id
            );

            box.classList.add("dragging");

        });


        // Stop dragging
        box.addEventListener("dragend", () => {

            box.classList.remove("dragging");

            removeDropIndicators();

        });


        // Dragging over an element
        box.addEventListener("dragover", (event) => {

            event.preventDefault();

            event.dataTransfer.dropEffect = "move";

            removeDropIndicators();

            const rect = box.getBoundingClientRect();

            const middle =
                rect.left + rect.width / 2;

            if (event.clientX < middle) {

                box.classList.add("drop-left");

            } else {

                box.classList.add("drop-right");

            }

        });


        // Drop
        box.addEventListener("drop", (event) => {

            event.preventDefault();

            const draggedId =
                event.dataTransfer.getData("text/plain");

            const rect =
                box.getBoundingClientRect();

            const middle =
                rect.left + rect.width / 2;

            const insertAfter =
                event.clientX >= middle;

            moveElement(
                draggedId,
                element.id,
                insertAfter
            );

            removeDropIndicators();

        });


        formulaCanvas.appendChild(box);

    });
}


function moveElement(
    draggedId,
    targetId,
    insertAfter
) {

    if (draggedId === targetId) {
        return;
    }


    const draggedIndex =
        formulaElements.findIndex(
            element =>
                element.id === draggedId
        );


    if (draggedIndex === -1) {
        return;
    }


    const draggedElement =
        formulaElements[draggedIndex];


    // Remove dragged element first
    formulaElements.splice(
        draggedIndex,
        1
    );


    let targetIndex =
        formulaElements.findIndex(
            element =>
                element.id === targetId
        );


    if (targetIndex === -1) {

        formulaElements.push(
            draggedElement
        );

        renderFormula();

        return;
    }


    if (insertAfter) {

        targetIndex++;

    }


    formulaElements.splice(
        targetIndex,
        0,
        draggedElement
    );


    renderFormula();
}


function removeDropIndicators() {

    document
        .querySelectorAll(
            ".drop-left, .drop-right"
        )
        .forEach(element => {

            element.classList.remove(
                "drop-left",
                "drop-right"
            );

        });

}


function showEditor(element) {

    const existing =
        document.getElementById(
            "element-editor"
        );

    if (existing) {
        existing.remove();
    }


    const editor =
        document.createElement("div");

    editor.id = "element-editor";


    editor.innerHTML = `

        <label>
            ${
                element.type === "variable"
                ? "Variable"
                : "Value"
            }
        </label>

        <input
            id="element-value"
            type="text"
            value="${element.value}"
            autofocus
        >


        ${
            element.type === "variable"
            ? `

                <label>
                    Meaning
                </label>

                <input
                    id="element-meaning"
                    type="text"
                    value="${element.meaning}"
                    placeholder="What does this variable mean?"
                >

            `
            : ""
        }


        <button id="save-element">
            Save
        </button>

        <button id="delete-element">
            Delete
        </button>

    `;


    document.body.appendChild(editor);


    document
        .getElementById(
            "save-element"
        )
        .addEventListener(
            "click",
            () => {

                element.value =
                    document
                        .getElementById(
                            "element-value"
                        )
                        .value;


                if (
                    element.type ===
                    "variable"
                ) {

                    element.meaning =
                        document
                            .getElementById(
                                "element-meaning"
                            )
                            .value;

                }


                editor.remove();

                renderFormula();

            }
        );


    document
        .getElementById(
            "delete-element"
        )
        .addEventListener(
            "click",
            () => {

                formulaElements =
                    formulaElements.filter(
                        item =>
                            item.id !==
                            element.id
                    );


                editor.remove();

                renderFormula();

            }
        );

}