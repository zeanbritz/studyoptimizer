// ============================================================
// FORMULA EDITOR
// ============================================================


// ============================================================
// INITIAL FORMULA
// ============================================================

let formulaElements = [];

if (
    typeof existingFormulaStructure !== "undefined"
    &&
    Array.isArray(existingFormulaStructure)
) {

    formulaElements =
        existingFormulaStructure;

}


// ============================================================
// DOM
// ============================================================

const formulaCanvas =
    document.getElementById(
        "formula-canvas"
    );

const formulaStructureInput =
    document.getElementById(
        "formula-structure"
    );


// ============================================================
// ID GENERATOR
// ============================================================

function createElementId() {

    if (
        window.crypto
        &&
        typeof window.crypto.randomUUID
        ===
        "function"
    ) {

        return window.crypto.randomUUID();

    }

    return (
        "formula-"
        +
        Date.now()
        +
        "-"
        +
        Math.random()
            .toString(16)
            .slice(2)
    );

}


// ============================================================
// GIVE OLD ELEMENTS IDS IF NECESSARY
// ============================================================

function ensureIds(
    elements
) {

    elements.forEach(
        function (element) {

            if (!element.id) {

                element.id =
                    createElementId();

            }

            if (
                element.type
                ===
                "fraction"
            ) {

                if (
                    !Array.isArray(
                        element.numerator
                    )
                ) {

                    element.numerator = [];

                }

                if (
                    !Array.isArray(
                        element.denominator
                    )
                ) {

                    element.denominator = [];

                }

                ensureIds(
                    element.numerator
                );

                ensureIds(
                    element.denominator
                );

            }

        }
    );

}


ensureIds(
    formulaElements
);


// ============================================================
// ACTIVE INSERTION LOCATION
// ============================================================

let activeContainer =
    formulaElements;

let insertionIndex =
    formulaElements.length;


// ============================================================
// KEYBOARD MODE
//
// It becomes true once the student clicks
// inside the formula.
// ============================================================

let formulaKeyboardActive =
    false;


// ============================================================
// UPDATE HIDDEN STRUCTURE INPUT
// ============================================================

function updateFormulaStructure() {

    if (!formulaStructureInput) {

        return;

    }

    formulaStructureInput.value =
        JSON.stringify(
            formulaElements
        );

}


// ============================================================
// FOCUS FORMULA
// ============================================================

function focusFormula() {

    formulaKeyboardActive =
        true;

    if (!formulaCanvas) {

        return;

    }

    try {

        formulaCanvas.focus(
            {
                preventScroll: true
            }
        );

    }

    catch (error) {

        formulaCanvas.focus();

    }

}


// ============================================================
// ADD ELEMENT
// ============================================================

function addElement(
    type,
    value = ""
) {

    const element = {

        id:
            createElementId(),

        type:
            type,

        value:
            value,

        meaning:
            ""

    };


    activeContainer.splice(
        insertionIndex,
        0,
        element
    );


    insertionIndex++;


    renderFormula();


    // --------------------------------------------------------
    // VARIABLE
    // --------------------------------------------------------

    if (
        type === "variable"
    ) {

        formulaKeyboardActive =
            false;

        showEditor(
            element
        );

        return;

    }


    // --------------------------------------------------------
    // MANUAL NUMBER BUTTON
    // --------------------------------------------------------

    if (
        type === "number"
        &&
        value === ""
    ) {

        formulaKeyboardActive =
            false;

        showEditor(
            element
        );

        return;

    }


    focusFormula();

}


// ============================================================
// KEYBOARD NUMBER
//
// Consecutive digits and one decimal point become
// one number:
//
// 2 . 4       -> 2.4
// 6 . 7 7 7   -> 6.777
// ============================================================

function addKeyboardDigit(
    character
) {

    const previousIndex =
        insertionIndex - 1;


    // ========================================================
    // CONTINUE EXISTING NUMBER
    // ========================================================

    if (
        previousIndex >= 0
    ) {

        const previous =
            activeContainer[
                previousIndex
            ];


        if (
            previous
            &&
            previous.type === "number"
        ) {

            const currentValue =
                String(
                    previous.value
                    ||
                    ""
                );


            // ------------------------------------------------
            // DECIMAL POINT
            //
            // ONLY ALLOW ONE DECIMAL POINT.
            // ------------------------------------------------

            if (
                character === "."
            ) {

                if (
                    currentValue.includes(
                        "."
                    )
                ) {

                    return;

                }


                previous.value =
                    currentValue
                    +
                    ".";

            }

            // ------------------------------------------------
            // DIGIT
            // ------------------------------------------------

            else {

                previous.value =
                    currentValue
                    +
                    character;

            }


            renderFormula();

            focusFormula();

            return;

        }

    }


    // ========================================================
    // START NEW NUMBER
    // ========================================================

    if (
        character === "."
    ) {

        // Typing "." first becomes 0.

        addElement(
            "number",
            "0."
        );

    }

    else {

        addElement(
            "number",
            character
        );

    }

}


// ============================================================
// RENDER FORMULA
// ============================================================

function renderFormula() {

    updateFormulaStructure();


    if (!formulaCanvas) {

        return;

    }


    formulaCanvas.innerHTML =
        "";


    renderContainer(
        formulaCanvas,
        formulaElements
    );

}


// ============================================================
// RENDER CONTAINER
// ============================================================

function renderContainer(
    parent,
    elements
) {

    const container =
        document.createElement(
            "div"
        );


    container.className =
        "formula-container";


    // ========================================================
    // EMPTY
    // ========================================================

    if (
        elements.length === 0
    ) {

        const emptyZone =
            document.createElement(
                "div"
            );


        emptyZone.className =
            "formula-empty-zone";


        emptyZone.title =
            "Click here, then type or add an element";


        emptyZone.addEventListener(
            "click",
            function (event) {

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


    // ========================================================
    // BEFORE FIRST ELEMENT
    // ========================================================

    if (
        elements.length > 0
    ) {

        addInsertionZone(
            container,
            elements,
            0
        );

    }


    // ========================================================
    // ELEMENTS
    // ========================================================

    elements.forEach(
        function (
            element,
            index
        ) {

            const box =
                document.createElement(
                    "div"
                );


            box.className =
                "formula-element";


            box.dataset.id =
                element.id;


            box.draggable =
                true;


            // =================================================
            // FRACTION
            // =================================================

            if (
                element.type
                ===
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
                    element.value
                    ||
                    "?";

            }


            // =================================================
            // DOUBLE CLICK EDIT
            // =================================================

            box.addEventListener(
                "dblclick",
                function (event) {

                    event.preventDefault();

                    event.stopPropagation();


                    if (
                        element.type
                        !==
                        "fraction"
                    ) {

                        formulaKeyboardActive =
                            false;


                        showEditor(
                            element
                        );

                    }

                }
            );


            // =================================================
            // DRAG START
            // =================================================

            box.addEventListener(
                "dragstart",
                function (event) {

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
                function () {

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
                function (event) {

                    event.preventDefault();

                    event.stopPropagation();


                    removeDropIndicators();


                    const rect =
                        box.getBoundingClientRect();


                    const middle =
                        rect.left
                        +
                        rect.width / 2;


                    if (
                        event.clientX
                        <
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
                function (event) {

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
                        rect.left
                        +
                        rect.width / 2;


                    const insertAfter =
                        event.clientX
                        >=
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
            // INSERTION ZONE AFTER
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


// ============================================================
// ADD INSERTION ZONE
// ============================================================

function addInsertionZone(
    container,
    elements,
    index
) {

    const zone =
        document.createElement(
            "div"
        );


    zone.className =
        "formula-insertion-zone";


    zone.title =
        "Insert here";


    zone.addEventListener(
        "click",
        function (event) {

            event.preventDefault();

            event.stopPropagation();


            selectInsertionPoint(
                elements,
                index,
                zone
            );

        }
    );


    container.appendChild(
        zone
    );

}


// ============================================================
// SELECT INSERTION POINT
// ============================================================

function selectInsertionPoint(
    elements,
    index,
    zone
) {

    activeContainer =
        elements;


    insertionIndex =
        index;


    document
        .querySelectorAll(
            ".formula-insertion-zone.active, .formula-empty-zone.active"
        )
        .forEach(
            function (element) {

                element.classList.remove(
                    "active"
                );

            }
        );


    if (zone) {

        zone.classList.add(
            "active"
        );

    }


    // ========================================================
    // CRITICAL:
    //
    // THIS ENABLES KEYBOARD INPUT.
    // ========================================================

    focusFormula();

}


// ============================================================
// FRACTION
// ============================================================

function renderFraction(
    box,
    fraction
) {

    const wrapper =
        document.createElement(
            "div"
        );


    wrapper.className =
        "fraction";


    // ========================================================
    // NUMERATOR
    // ========================================================

    const numerator =
        document.createElement(
            "div"
        );


    numerator.className =
        "fraction-numerator";


    renderContainer(
        numerator,
        fraction.numerator
    );


    // ========================================================
    // LINE
    // ========================================================

    const line =
        document.createElement(
            "div"
        );


    line.className =
        "fraction-line";


    // ========================================================
    // DENOMINATOR
    // ========================================================

    const denominator =
        document.createElement(
            "div"
        );


    denominator.className =
        "fraction-denominator";


    renderContainer(
        denominator,
        fraction.denominator
    );


    wrapper.appendChild(
        numerator
    );


    wrapper.appendChild(
        line
    );


    wrapper.appendChild(
        denominator
    );


    box.appendChild(
        wrapper
    );

}


// ============================================================
// ADD FRACTION
// ============================================================

function addFraction() {

    const fraction = {

        id:
            createElementId(),

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


    activeContainer.splice(
        insertionIndex,
        0,
        fraction
    );


    activeContainer =
        fraction.numerator;


    insertionIndex =
        0;


    renderFormula();


    focusFormula();

}


// ============================================================
// REMOVE ELEMENT
// ============================================================

function removeElement(
    elements,
    id
) {

    const index =
        elements.findIndex(
            function (element) {

                return (
                    element.id
                    ===
                    id
                );

            }
        );


    if (
        index !== -1
    ) {

        elements.splice(
            index,
            1
        );


        return true;

    }


    for (
        const element
        of
        elements
    ) {

        if (
            element.type
            ===
            "fraction"
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


// ============================================================
// FIND AND REMOVE
// ============================================================

function findAndRemoveElement(
    elements,
    id
) {

    const index =
        elements.findIndex(
            function (element) {

                return (
                    element.id
                    ===
                    id
                );

            }
        );


    if (
        index !== -1
    ) {

        return elements.splice(
            index,
            1
        )[0];

    }


    for (
        const element
        of
        elements
    ) {

        if (
            element.type
            ===
            "fraction"
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


// ============================================================
// MOVE ELEMENT
// ============================================================

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
            function (element) {

                return (
                    element.id
                    ===
                    targetId
                );

            }
        );


    if (
        targetIndex === -1
    ) {

        targetContainer.push(
            dragged
        );


        targetIndex =
            targetContainer.length - 1;

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


    activeContainer =
        targetContainer;


    insertionIndex =
        targetIndex + 1;


    renderFormula();


    focusFormula();

}


// ============================================================
// REMOVE DRAG INDICATORS
// ============================================================

function removeDropIndicators() {

    document
        .querySelectorAll(
            ".drop-left, .drop-right"
        )
        .forEach(
            function (element) {

                element.classList.remove(
                    "drop-left",
                    "drop-right"
                );

            }
        );

}


// ============================================================
// ELEMENT EDITOR
// ============================================================

function showEditor(
    element
) {

    const existing =
        document.getElementById(
            "element-editor"
        );


    if (existing) {

        existing.remove();

    }


    const editor =
        document.createElement(
            "div"
        );


    editor.id =
        "element-editor";


    let title =
        "Edit Element";


    let label =
        "Value";


    let placeholder =
        "Enter value";


    if (
        element.type
        ===
        "variable"
    ) {

        title =
            "Define Variable";


        label =
            "Symbol";


        placeholder =
            "e.g. PV";

    }


    if (
        element.type
        ===
        "number"
    ) {

        title =
            "Enter Number";


        label =
            "Number";


        placeholder =
            "e.g. 100";

    }


    editor.innerHTML = `

        <h3>
            ${title}
        </h3>

        <label>
            ${label}
        </label>

        <input
            id="element-value"
            type="text"
            value="${element.value || ""}"
            placeholder="${placeholder}"
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
                        placeholder="e.g. Present Value"
                    >

                `
                :
                ""
        }

        <div style="margin-top: 15px;">

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

        </div>

    `;


    document.body.appendChild(
        editor
    );


    const valueInput =
        document.getElementById(
            "element-value"
        );


    valueInput.focus();


    // ========================================================
    // SAVE
    // ========================================================

    document
        .getElementById(
            "save-element"
        )
        .addEventListener(
            "click",
            function () {

                const value =
                    valueInput
                    .value
                    .trim();


                if (!value) {

                    return;

                }


                // ------------------------------------------------
                // NUMBER MUST BE NUMERIC
                // ------------------------------------------------

                if (
                    element.type
                    ===
                    "number"
                ) {

                    if (
                        !/^(?:\d+\.?\d*|\.\d+)$/.test(
                            value
                        )
                    ) {

                        valueInput.focus();

                        return;

                    }

                }


                element.value =
                    value;


                if (
                    element.type
                    ===
                    "variable"
                ) {

                    const meaningInput =
                        document.getElementById(
                            "element-meaning"
                        );


                    element.meaning =
                        meaningInput
                        ?
                        meaningInput.value.trim()
                        :
                        "";

                }


                editor.remove();


                renderFormula();


                focusFormula();

            }
        );


    // ========================================================
    // DELETE
    // ========================================================

    document
        .getElementById(
            "delete-element"
        )
        .addEventListener(
            "click",
            function () {

                removeElement(
                    formulaElements,
                    element.id
                );


                editor.remove();


                activeContainer =
                    formulaElements;


                insertionIndex =
                    formulaElements.length;


                renderFormula();


                focusFormula();

            }
        );


    // ========================================================
    // ENTER SAVES
    // ========================================================

    editor
        .querySelectorAll(
            "input"
        )
        .forEach(
            function (input) {

                input.addEventListener(
                    "keydown",
                    function (event) {

                        if (
                            event.key
                            ===
                            "Enter"
                        ) {

                            event.preventDefault();


                            document
                                .getElementById(
                                    "save-element"
                                )
                                .click();

                        }

                    }
                );

            }
        );

}


// ============================================================
// TOOLBAR BUTTONS
// ============================================================

const addVariableButton =
    document.getElementById(
        "add-variable-button"
    );


if (addVariableButton) {

    addVariableButton.addEventListener(
        "click",
        function () {

            addElement(
                "variable"
            );

        }
    );

}


const addNumberButton =
    document.getElementById(
        "add-number-button"
    );


if (addNumberButton) {

    addNumberButton.addEventListener(
        "click",
        function () {

            addElement(
                "number"
            );

        }
    );

}


const addFractionButton =
    document.getElementById(
        "add-fraction-button"
    );


if (addFractionButton) {

    addFractionButton.addEventListener(
        "click",
        function () {

            addFraction();

        }
    );

}


// ============================================================
// PICKERS
// ============================================================

function closeAllPickers() {

    document
        .querySelectorAll(
            ".formula-picker.open"
        )
        .forEach(
            function (picker) {

                picker.classList.remove(
                    "open"
                );

            }
        );

}


// ============================================================
// PICKER TOGGLE
// ============================================================

document
    .querySelectorAll(
        ".picker-toggle"
    )
    .forEach(
        function (button) {

            button.addEventListener(
                "click",
                function (event) {

                    event.preventDefault();

                    event.stopPropagation();


                    const picker =
                        button.closest(
                            ".formula-picker"
                        );


                    const isOpen =
                        picker.classList.contains(
                            "open"
                        );


                    closeAllPickers();


                    if (!isOpen) {

                        picker.classList.add(
                            "open"
                        );

                    }

                }
            );

        }
    );


// ============================================================
// PICKER CHOICE
// ============================================================

document
    .querySelectorAll(
        ".picker-choice"
    )
    .forEach(
        function (button) {

            button.addEventListener(
                "click",
                function (event) {

                    event.preventDefault();

                    event.stopPropagation();


                    const type =
                        button.dataset
                        .elementType;


                    const value =
                        button.dataset
                        .elementValue;


                    addElement(
                        type,
                        value
                    );


                    closeAllPickers();


                    focusFormula();

                }
            );

        }
    );


// ============================================================
// DON'T CLOSE WHEN CLICKING INSIDE MENU
// ============================================================

document
    .querySelectorAll(
        ".formula-picker"
    )
    .forEach(
        function (picker) {

            picker.addEventListener(
                "click",
                function (event) {

                    event.stopPropagation();

                }
            );

        }
    );


// ============================================================
// CLICK OUTSIDE CLOSES MENUS
// ============================================================

document.addEventListener(
    "click",
    function () {

        closeAllPickers();

    }
);


// ============================================================
// KEYBOARD OPERATORS
// ============================================================

const keyboardOperators = {

    "+":
        "+",

    "-":
        "-",

    "−":
        "-",

    "*":
        "×",

    "×":
        "×",

    "/":
        "÷",

    "÷":
        "÷",

    "=":
        "=",

    "<":
        "<",

    ">":
        ">"

};


// ============================================================
// GLOBAL KEYBOARD INPUT
//
// We listen on DOCUMENT, not just the canvas.
//
// The keyboard becomes active after the student
// clicks a formula insertion point / canvas.
// ============================================================

document.addEventListener(
    "keydown",
    function (event) {

        if (
            !formulaKeyboardActive
        ) {

            return;

        }


        // ----------------------------------------------------
        // NORMAL SHORTCUTS
        // ----------------------------------------------------

        if (
            event.ctrlKey
            ||
            event.metaKey
            ||
            event.altKey
        ) {

            return;

        }


        // ----------------------------------------------------
        // DON'T INTERFERE WITH FORM FIELDS
        // ----------------------------------------------------

        const activeElement =
            document.activeElement;


        if (activeElement) {

            const tag =
                activeElement
                .tagName
                .toLowerCase();


            if (
                tag === "input"
                ||
                tag === "textarea"
                ||
                tag === "select"
                ||
                activeElement.isContentEditable
            ) {

                return;

            }

        }


        const key =
            event.key;


        // ====================================================
        // NUMBER
        //
        // ALLOW:
        // 0-9
        // one decimal point
        // ====================================================

        if (
            /^[0-9.]$/.test(
                key
            )
        ) {

            event.preventDefault();


            addKeyboardDigit(
                key
            );


            return;

        }


        // ====================================================
        // OPERATOR
        // ====================================================

        if (
            Object.prototype
            .hasOwnProperty
            .call(
                keyboardOperators,
                key
            )
        ) {

            event.preventDefault();


            addElement(
                "operator",
                keyboardOperators[
                    key
                ]
            );


            return;

        }

    }
);


// ============================================================
// CLICKING CANVAS ACTIVATES KEYBOARD
// ============================================================

if (formulaCanvas) {

    formulaCanvas.addEventListener(
        "click",
        function (event) {

            if (
                event.target
                ===
                formulaCanvas
            ) {

                activeContainer =
                    formulaElements;


                insertionIndex =
                    formulaElements.length;


                focusFormula();

            }

        }
    );

}


// ============================================================
// LEAVING THE FORMULA FOR AN INPUT DISABLES FORMULA KEYBOARD
// ============================================================

document.addEventListener(
    "focusin",
    function (event) {

        const target =
            event.target;


        if (
            !target
        ) {

            return;

        }


        if (
            target ===
            formulaCanvas
        ) {

            formulaKeyboardActive =
                true;


            return;

        }


        const tag =
            target
            .tagName
            .toLowerCase();


        if (
            tag === "input"
            ||
            tag === "textarea"
            ||
            tag === "select"
        ) {

            formulaKeyboardActive =
                false;

        }

    }
);


// ============================================================
// INITIAL RENDER
// ============================================================

renderFormula();