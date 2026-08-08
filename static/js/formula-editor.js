let formulaElements = [];

const formulaCanvas =
    document.getElementById("formula-canvas");


// =====================================================
// ACTIVE INSERTION LOCATION
// =====================================================

let activeContainer = formulaElements;
let insertionIndex = 0;


// =====================================================
// ADD ELEMENT
// =====================================================

function addElement(type, value = "") {

    const element = {
        id: crypto.randomUUID(),
        type: type,
        value: value,
        meaning: ""
    };

    activeContainer.splice(
        insertionIndex,
        0,
        element
    );

    insertionIndex++;

    renderFormula();
}


// =====================================================
// RENDER FORMULA
// =====================================================

function renderFormula() {

    formulaCanvas.innerHTML = "";

    renderContainer(
        formulaCanvas,
        formulaElements
    );
}


// =====================================================
// RENDER CONTAINER
// =====================================================

function renderContainer(
    parent,
    elements
) {

    const container =
        document.createElement("div");

    container.className =
        "formula-container";


    // =================================================
    // EMPTY CONTAINER
    // =================================================

    if (elements.length === 0) {

        const emptyZone =
            document.createElement("div");

        emptyZone.className =
            "formula-empty-zone";

        emptyZone.title =
            "Click to insert here";


        emptyZone.addEventListener(
            "click",
            function(event) {

                event.preventDefault();
                event.stopPropagation();


                selectInsertionPoint(
                    elements,
                    0,
                    emptyZone
                );

            }
        );


        container.appendChild(
            emptyZone
        );

    }


    // =================================================
    // INSERTION ZONE BEFORE FIRST ELEMENT
    // =================================================

    if (elements.length > 0) {

        addInsertionZone(
            container,
            elements,
            0
        );

    }


    // =================================================
    // ELEMENTS
    // =================================================

    elements.forEach(
        function(element, index) {

            const box =
                document.createElement(
                    "div"
                );

            box.className =
                "formula-element";

            box.dataset.id =
                element.id;

            box.draggable = true;


            // =================================================
            // FRACTION
            // =================================================

            if (
                element.type ===
                "fraction"
            ) {

                renderFraction(
                    box,
                    element
                );

            }

            // =================================================
            // NORMAL ELEMENT
            // =================================================

            else {

                box.textContent =
                    element.value ||
                    "?";

            }


            // =================================================
            // DOUBLE CLICK EDIT
            // =================================================

            box.addEventListener(
                "dblclick",
                function(event) {

                    event.preventDefault();
                    event.stopPropagation();

                    showEditor(
                        element
                    );

                }
            );


            // =================================================
            // DRAG START
            // =================================================

            box.addEventListener(
                "dragstart",
                function(event) {

                    event.stopPropagation();

                    event.dataTransfer
                        .effectAllowed =
                        "move";

                    event.dataTransfer
                        .setData(
                            "text/plain",
                            element.id
                        );

                    box.classList.add(
                        "dragging"
                    );

                }
            );


            // =================================================
            // DRAG END
            // =================================================

            box.addEventListener(
                "dragend",
                function() {

                    box.classList.remove(
                        "dragging"
                    );

                    removeDropIndicators();

                }
            );


            // =================================================
            // DRAG OVER
            // =================================================

            box.addEventListener(
                "dragover",
                function(event) {

                    event.preventDefault();

                    event.stopPropagation();

                    removeDropIndicators();


                    const rect =
                        box.getBoundingClientRect();

                    const middle =
                        rect.left +
                        rect.width / 2;


                    if (
                        event.clientX <
                        middle
                    ) {

                        box.classList.add(
                            "drop-left"
                        );

                    }

                    else {

                        box.classList.add(
                            "drop-right"
                        );

                    }

                }
            );


            // =================================================
            // DROP
            // =================================================

            box.addEventListener(
                "drop",
                function(event) {

                    event.preventDefault();

                    event.stopPropagation();


                    const draggedId =
                        event.dataTransfer
                            .getData(
                                "text/plain"
                            );


                    const rect =
                        box.getBoundingClientRect();

                    const middle =
                        rect.left +
                        rect.width / 2;


                    const insertAfter =
                        event.clientX >=
                        middle;


                    moveElement(
                        draggedId,
                        elements,
                        element.id,
                        insertAfter
                    );


                    removeDropIndicators();

                }
            );


            container.appendChild(
                box
            );


            // =================================================
            // INSERTION ZONE AFTER ELEMENT
            // =================================================

            addInsertionZone(
                container,
                elements,
                index + 1
            );

        }
    );


    parent.appendChild(
        container
    );
}

// =====================================================
// INSERTION ZONE
// =====================================================

function addInsertionZone(
    container,
    elements,
    index
) {

    const zone =
        document.createElement("div");

    zone.className =
        "formula-insertion-zone";

    zone.title =
        "Insert here";


    zone.addEventListener(
        "click",
        function(event) {

            event.preventDefault();
            event.stopPropagation();


            // Set the active container

            activeContainer =
                elements;


            // Set exact insertion position

            insertionIndex =
                index;


            // Remove all previous
            // insertion highlights

            document
                .querySelectorAll(
                    ".formula-insertion-zone.active"
                )
                .forEach(
                    function(element) {

                        element.classList.remove(
                            "active"
                        );

                    }
                );


            // Highlight this position

            zone.classList.add(
                "active"
            );

        }
    );


    container.appendChild(
        zone
    );
}


// =====================================================
// SELECT INSERTION POINT
// =====================================================

function selectInsertionPoint(
    elements,
    index,
    zone
) {

    activeContainer =
        elements;

    insertionIndex =
        index;


    /*
     * Remove previous blue line.
     */

    document
        .querySelectorAll(
            ".formula-insertion-zone.active"
        )
        .forEach(
            function(element) {

                element.classList.remove(
                    "active"
                );

            }
        );


    /*
     * Show blue insertion line.
     */

    zone.classList.add(
        "active"
    );

}


// =====================================================
// FRACTION
// =====================================================

function renderFraction(box, fraction) {

    const wrapper =
        document.createElement("div");

    wrapper.className = "fraction";


    // =================================================
    // NUMERATOR
    // =================================================

    const numerator =
        document.createElement("div");

    numerator.className =
        "fraction-numerator";


    renderContainer(
        numerator,
        fraction.numerator
    );


    // =================================================
    // FRACTION LINE
    // =================================================

    const line =
        document.createElement("div");

    line.className =
        "fraction-line";


    // =================================================
    // DENOMINATOR
    // =================================================

    const denominator =
        document.createElement("div");

    denominator.className =
        "fraction-denominator";


    renderContainer(
        denominator,
        fraction.denominator
    );


    // =================================================
    // ADD EVERYTHING
    // =================================================

    wrapper.appendChild(
        numerator
    );

    wrapper.appendChild(
        line
    );

    wrapper.appendChild(
        denominator
    );


    // =================================================
    // STOP EVENTS ESCAPING FRACTION
    // =================================================

    box.appendChild(
        wrapper
    );
}


// =====================================================
// ADD FRACTION
// =====================================================

function addFraction() {

    const fraction = {

        id:
            crypto.randomUUID(),

        type:
            "fraction",

        value:
            "",

        meaning:
            "",

        numerator:
            [],

        denominator:
            []

    };


    // Add fraction at current position

    activeContainer.splice(
        insertionIndex,
        0,
        fraction
    );


    /*
     * Remember where the fraction
     * was inserted.
     */

    const fractionContainer =
        activeContainer;


    /*
     * Move the insertion point
     * inside the numerator.
     */

    activeContainer =
        fraction.numerator;

    insertionIndex = 0;


    renderFormula();


    /*
     * Find the first insertion zone
     * inside the newly created fraction.
     */

    const numeratorZone =
        document.querySelector(
            ".fraction-numerator .formula-insertion-zone"
        );


    if (numeratorZone) {

        numeratorZone.classList.add(
            "active"
        );

    }

}

// =====================================================
// OPERATOR
// =====================================================

function addSelectedOperator() {

    const select =
        document.getElementById(
            "operator-select"
        );

    const operator =
        select.value;


    if (!operator) {
        return;
    }


    addElement(
        "operator",
        operator
    );


    select.value = "";
}


// =====================================================
// MOVE ELEMENT
// =====================================================

function moveElement(
    draggedId,
    targetContainer,
    targetId,
    insertAfter
) {

    const dragged =
        findAndRemoveElement(
            formulaElements,
            draggedId
        );


    if (!dragged) {
        return;
    }


    let targetIndex =
        targetContainer.findIndex(
            function(element) {

                return element.id ===
                    targetId;

            }
        );


    if (targetIndex === -1) {

        targetContainer.push(
            dragged
        );

    }
    else {

        if (insertAfter) {

            targetIndex++;

        }

        targetContainer.splice(
            targetIndex,
            0,
            dragged
        );

    }


    renderFormula();
}


// =====================================================
// FIND AND REMOVE ELEMENT
// =====================================================

function findAndRemoveElement(
    elements,
    id
) {

    const index =
        elements.findIndex(
            function(element) {

                return element.id === id;

            }
        );


    if (index !== -1) {

        return elements.splice(
            index,
            1
        )[0];

    }


    for (
        const element of elements
    ) {

        if (
            element.type === "fraction"
        ) {

            const numeratorResult =
                findAndRemoveElement(
                    element.numerator,
                    id
                );


            if (numeratorResult) {

                return numeratorResult;

            }


            const denominatorResult =
                findAndRemoveElement(
                    element.denominator,
                    id
                );


            if (denominatorResult) {

                return denominatorResult;

            }

        }

    }


    return null;
}


// =====================================================
// EDITOR
// =====================================================

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


    editor.id =
        "element-editor";


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
            value="${element.value || ""}"
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
                        value="${element.meaning || ""}"
                        placeholder="What does this variable mean?"
                    >

                `
                : ""
        }


        <button
            id="save-element"
            type="button"
        >
            Save
        </button>


        <button
            id="delete-element"
            type="button"
        >
            Delete
        </button>

    `;


    document.body.appendChild(
        editor
    );


    // =================================================
    // SAVE
    // =================================================

    document
        .getElementById(
            "save-element"
        )
        .addEventListener(
            "click",
            function() {

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


    // =================================================
    // DELETE
    // =================================================

    document
        .getElementById(
            "delete-element"
        )
        .addEventListener(
            "click",
            function() {

                removeElement(
                    formulaElements,
                    element.id
                );


                editor.remove();

                renderFormula();

            }
        );
}


// =====================================================
// REMOVE ELEMENT
// =====================================================

function removeElement(
    elements,
    id
) {

    const index =
        elements.findIndex(
            function(element) {

                return element.id === id;

            }
        );


    if (index !== -1) {

        elements.splice(
            index,
            1
        );

        return true;

    }


    for (
        const element of elements
    ) {

        if (
            element.type === "fraction"
        ) {

            if (
                removeElement(
                    element.numerator,
                    id
                )
            ) {

                return true;

            }


            if (
                removeElement(
                    element.denominator,
                    id
                )
            ) {

                return true;

            }

        }

    }


    return false;
}


// =====================================================
// REMOVE DROP INDICATORS
// =====================================================

function removeDropIndicators() {

    document
        .querySelectorAll(
            ".drop-left, .drop-right"
        )
        .forEach(
            function(element) {

                element.classList.remove(
                    "drop-left",
                    "drop-right"
                );

            }
        );
}


// =====================================================
// INITIAL RENDER
// =====================================================

renderFormula();