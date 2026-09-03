// ============================================================
// FORMULA EDITOR
// ============================================================


// ============================================================
// EXISTING FORMULA
// ============================================================

let formulaElements = [];


if (
    typeof existingFormulaStructure
    !==
    "undefined"
    &&
    Array.isArray(
        existingFormulaStructure
    )
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
// PREVIOUS VARIABLE MEANINGS
// ============================================================

let formulaVariableSuggestions =
    {};


const variableSuggestionDataElement =
    document.getElementById(
        "formula-variable-suggestions-data"
    );


if (
    variableSuggestionDataElement
) {

    try {

        formulaVariableSuggestions =
            JSON.parse(
                variableSuggestionDataElement
                    .textContent
            );

    }

    catch (
        error
    ) {

        formulaVariableSuggestions =
            {};

    }

}


// ============================================================
// FIND PREVIOUS MEANINGS
// ============================================================

function getPreviousMeanings(
    symbol
) {

    const key =
        String(
            symbol
            ||
            ""
        )
        .trim()
        .toLowerCase();


    if (!key) {

        return [];

    }


    const suggestions =
        formulaVariableSuggestions[
            key
        ];


    if (
        !Array.isArray(
            suggestions
        )
    ) {

        return [];

    }


    return suggestions;

}


// ============================================================
// ID
// ============================================================

function createElementId() {

    if (
        window.crypto
        &&
        typeof window.crypto.randomUUID
        ===
        "function"
    ) {

        return (
            window.crypto.randomUUID()
        );

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
// ENSURE IDS
// ============================================================

function ensureIds(
    elements
) {

    elements.forEach(
        function (
            element
        ) {

            if (
                !element.id
            ) {

                element.id =
                    createElementId();

            }


            if (
                typeof element.meaning
                !==
                "string"
            ) {

                element.meaning =
                    "";

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

                    element.numerator =
                        [];

                }


                if (
                    !Array.isArray(
                        element.denominator
                    )
                ) {

                    element.denominator =
                        [];

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
// INSERTION LOCATION
// ============================================================

let activeContainer =
    formulaElements;


let insertionIndex =
    formulaElements.length;


let formulaKeyboardActive =
    false;


// ============================================================
// UPDATE STRUCTURE
// ============================================================

function updateFormulaStructure() {

    if (
        !formulaStructureInput
    ) {

        return;

    }


    formulaStructureInput.value =
        JSON.stringify(
            formulaElements
        );

}


// ============================================================
// FOCUS
// ============================================================

function focusFormula() {

    formulaKeyboardActive =
        true;


    if (
        !formulaCanvas
    ) {

        return;

    }


    try {

        formulaCanvas.focus(
            {
                preventScroll:
                    true
            }
        );

    }

    catch (
        error
    ) {

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


    if (
        type
        ===
        "variable"
    ) {

        formulaKeyboardActive =
            false;


        showEditor(
            element
        );


        return;

    }


    if (
        type
        ===
        "symbol"
    ) {

        formulaKeyboardActive =
            false;


        showEditor(
            element
        );


        return;

    }


    if (
        type
        ===
        "number"
        &&
        value
        ===
        ""
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
// ============================================================

function addKeyboardNumberCharacter(
    character
) {

    const previousIndex =
        insertionIndex
        -
        1;


    if (
        previousIndex
        >=
        0
    ) {

        const previous =
            activeContainer[
                previousIndex
            ];


        if (
            previous
            &&
            previous.type
            ===
            "number"
        ) {

            const currentValue =
                String(
                    previous.value
                    ||
                    ""
                );


            if (
                character
                ===
                "."
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


    if (
        character
        ===
        "."
    ) {

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
// RENDER
// ============================================================

function renderFormula() {

    updateFormulaStructure();


    if (
        !formulaCanvas
    ) {

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


    if (
        elements.length
        ===
        0
    ) {

        const emptyZone =
            document.createElement(
                "div"
            );


        emptyZone.className =
            "formula-empty-zone";


        emptyZone.addEventListener(
            "click",
            function (
                event
            ) {

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


    if (
        elements.length
        >
        0
    ) {

        addInsertionZone(
            container,
            elements,
            0
        );

    }


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

            else {

                box.textContent =
                    element.value
                    ||
                    "?";

            }


            if (
                element.meaning
            ) {

                box.title =
                    element.meaning;

            }


            box.addEventListener(
                "dblclick",
                function (
                    event
                ) {

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


            box.addEventListener(
                "dragstart",
                function (
                    event
                ) {

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


            box.addEventListener(
                "dragend",
                function () {

                    box.classList.remove(
                        "dragging"
                    );


                    removeDropIndicators();

                }
            );


            box.addEventListener(
                "dragover",
                function (
                    event
                ) {

                    event.preventDefault();


                    removeDropIndicators();


                    const rect =
                        box
                        .getBoundingClientRect();


                    const middle =
                        rect.left
                        +
                        rect.width
                        /
                        2;


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


            box.addEventListener(
                "drop",
                function (
                    event
                ) {

                    event.preventDefault();


                    const draggedId =
                        event.dataTransfer
                        .getData(
                            "text/plain"
                        );


                    const rect =
                        box
                        .getBoundingClientRect();


                    const insertAfter =
                        (
                            event.clientX
                            >=
                            (
                                rect.left
                                +
                                rect.width / 2
                            )
                        );


                    moveElement(
                        draggedId,
                        elements,
                        element.id,
                        insertAfter
                    );

                }
            );


            container.appendChild(
                box
            );


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
// INSERTION ZONE
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


    zone.addEventListener(
        "click",
        function (
            event
        ) {

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
// SELECT INSERTION
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
            function (
                element
            ) {

                element.classList.remove(
                    "active"
                );

            }
        );


    if (
        zone
    ) {

        zone.classList.add(
            "active"
        );

    }


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


    const line =
        document.createElement(
            "div"
        );


    line.className =
        "fraction-line";


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
// REMOVE
// ============================================================

function removeElement(
    elements,
    id
) {

    const index =
        elements.findIndex(
            element =>
                element.id
                ===
                id
        );


    if (
        index
        !==
        -1
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
            element =>
                element.id
                ===
                id
        );


    if (
        index
        !==
        -1
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

            const numerator =
                findAndRemoveElement(
                    element.numerator,
                    id
                );


            if (
                numerator
            ) {

                return numerator;

            }


            const denominator =
                findAndRemoveElement(
                    element.denominator,
                    id
                );


            if (
                denominator
            ) {

                return denominator;

            }

        }

    }


    return null;

}


// ============================================================
// MOVE
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


    if (
        !dragged
    ) {

        return;

    }


    let targetIndex =
        targetContainer.findIndex(
            element =>
                element.id
                ===
                targetId
        );


    if (
        targetIndex
        ===
        -1
    ) {

        targetContainer.push(
            dragged
        );


        targetIndex =
            targetContainer.length
            -
            1;

    }

    else {

        if (
            insertAfter
        ) {

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
        targetIndex
        +
        1;


    renderFormula();


    focusFormula();

}


// ============================================================
// DRAG INDICATORS
// ============================================================

function removeDropIndicators() {

    document
        .querySelectorAll(
            ".drop-left, .drop-right"
        )
        .forEach(
            function (
                element
            ) {

                element.classList.remove(
                    "drop-left",
                    "drop-right"
                );

            }
        );

}


// ============================================================
// HTML ATTRIBUTE ESCAPE
// ============================================================

function escapeAttribute(
    value
) {

    return String(
        value
        ||
        ""
    )
        .replace(
            /&/g,
            "&amp;"
        )
        .replace(
            /"/g,
            "&quot;"
        )
        .replace(
            /</g,
            "&lt;"
        )
        .replace(
            />/g,
            "&gt;"
        );

}


// ============================================================
// EDITOR
// ============================================================

function showEditor(
    element
) {

    const existing =
        document.getElementById(
            "element-editor"
        );


    if (
        existing
    ) {

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


    let valueReadOnly =
        false;


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
            "e.g. rf";

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
            "e.g. 2.4";

    }


    if (
        element.type
        ===
        "symbol"
    ) {

        title =
            "Describe Symbol";


        label =
            "Symbol";


        valueReadOnly =
            true;

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
            value="${escapeAttribute(element.value)}"
            placeholder="${placeholder}"
            ${valueReadOnly ? "readonly" : ""}
        >


        ${
            element.type
            ===
            "variable"

                ? `

                    <label>
                        Meaning
                    </label>


                    <input
                        id="element-meaning"
                        type="text"
                        value="${escapeAttribute(element.meaning)}"
                        placeholder="e.g. Risk free rate"
                        autocomplete="off"
                    >


                    <div
                        id="previous-meaning-wrapper"
                        style="
                            display: none;
                            margin-top: 10px;
                        "
                    >

                        <label>
                            Previous meanings
                        </label>


                        <select
                            id="previous-meaning-select"
                            style="
                                width: 100%;
                                padding: 9px;
                                border: 1px solid #ccc;
                                border-radius: 7px;
                                background: white;
                            "
                        >

                            <option value="">
                                Choose a previous meaning...
                            </option>

                        </select>

                    </div>

                `

                :
                ""
        }


        ${
            element.type
            ===
            "symbol"

                ? `

                    <label>
                        Description
                        <span
                            style="
                                color: #999;
                                font-size: 11px;
                            "
                        >
                            Optional
                        </span>
                    </label>


                    <input
                        id="element-meaning"
                        type="text"
                        value="${escapeAttribute(element.meaning)}"
                        placeholder="e.g. Sum of all values"
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


    const meaningInput =
        document.getElementById(
            "element-meaning"
        );


    const previousMeaningWrapper =
        document.getElementById(
            "previous-meaning-wrapper"
        );


    const previousMeaningSelect =
        document.getElementById(
            "previous-meaning-select"
        );


    // ========================================================
    // PREVIOUS MEANING DROPDOWN
    // ========================================================

    function refreshPreviousMeanings() {

        if (
            element.type
            !==
            "variable"
            ||
            !previousMeaningWrapper
            ||
            !previousMeaningSelect
        ) {

            return;

        }


        const meanings =
            getPreviousMeanings(
                valueInput.value
            );


        previousMeaningSelect.innerHTML =
            `

                <option value="">
                    Choose a previous meaning...
                </option>

            `;


        if (
            meanings.length
            ===
            0
        ) {

            previousMeaningWrapper.style.display =
                "none";


            return;

        }


        meanings.forEach(
            function (
                meaning
            ) {

                const option =
                    document.createElement(
                        "option"
                    );


                option.value =
                    meaning;


                option.textContent =
                    meaning;


                previousMeaningSelect.appendChild(
                    option
                );

            }
        );


        previousMeaningWrapper.style.display =
            "block";

    }


    if (
        element.type
        ===
        "variable"
    ) {

        valueInput.addEventListener(
            "input",
            refreshPreviousMeanings
        );


        valueInput.addEventListener(
            "change",
            refreshPreviousMeanings
        );


        if (
            previousMeaningSelect
        ) {

            previousMeaningSelect.addEventListener(
                "change",
                function () {

                    if (
                        previousMeaningSelect.value
                        &&
                        meaningInput
                    ) {

                        meaningInput.value =
                            previousMeaningSelect.value;


                        meaningInput.focus();

                    }

                }
            );

        }


        refreshPreviousMeanings();

    }


    // ========================================================
    // FOCUS
    // ========================================================

    if (
        element.type
        ===
        "symbol"
        &&
        meaningInput
    ) {

        meaningInput.focus();

    }

    else {

        valueInput.focus();


        if (
            !valueReadOnly
        ) {

            valueInput.select();

        }

    }


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


                if (
                    !value
                ) {

                    return;

                }


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
                    ||
                    element.type
                    ===
                    "symbol"
                ) {

                    element.meaning =
                        meaningInput
                        ?
                        meaningInput
                            .value
                            .trim()
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
            function (
                input
            ) {

                input.addEventListener(
                    "keydown",
                    function (
                        event
                    ) {

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
// TOOLBAR
// ============================================================

const addVariableButton =
    document.getElementById(
        "add-variable-button"
    );


if (
    addVariableButton
) {

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


if (
    addNumberButton
) {

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


if (
    addFractionButton
) {

    addFractionButton.addEventListener(
        "click",
        addFraction
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
            function (
                picker
            ) {

                picker.classList.remove(
                    "open"
                );

            }
        );

}


document
    .querySelectorAll(
        ".picker-toggle"
    )
    .forEach(
        function (
            button
        ) {

            button.addEventListener(
                "click",
                function (
                    event
                ) {

                    event.preventDefault();

                    event.stopPropagation();


                    const picker =
                        button.closest(
                            ".formula-picker"
                        );


                    const open =
                        picker.classList.contains(
                            "open"
                        );


                    closeAllPickers();


                    if (
                        !open
                    ) {

                        picker.classList.add(
                            "open"
                        );

                    }

                }
            );

        }
    );


document
    .querySelectorAll(
        ".picker-choice"
    )
    .forEach(
        function (
            button
        ) {

            button.addEventListener(
                "click",
                function (
                    event
                ) {

                    event.preventDefault();

                    event.stopPropagation();


                    const type =
                        button.dataset
                        .elementType;


                    const value =
                        button.dataset
                        .elementValue;


                    closeAllPickers();


                    addElement(
                        type,
                        value
                    );

                }
            );

        }
    );


document.addEventListener(
    "click",
    closeAllPickers
);


// ============================================================
// KEYBOARD
// ============================================================

const keyboardOperators = {

    "+":
        "+",

    "-":
        "-",

    "*":
        "×",

    "/":
        "÷",

    "=":
        "=",

    "<":
        "<",

    ">":
        ">"

};


document.addEventListener(
    "keydown",
    function (
        event
    ) {

        if (
            !formulaKeyboardActive
        ) {

            return;

        }


        if (
            event.ctrlKey
            ||
            event.metaKey
            ||
            event.altKey
        ) {

            return;

        }


        const active =
            document.activeElement;


        if (
            active
        ) {

            const tag =
                active.tagName
                .toLowerCase();


            if (
                tag
                ===
                "input"
                ||
                tag
                ===
                "textarea"
                ||
                tag
                ===
                "select"
            ) {

                return;

            }

        }


        const key =
            event.key;


        if (
            /^[0-9.]$/.test(
                key
            )
        ) {

            event.preventDefault();


            addKeyboardNumberCharacter(
                key
            );


            return;

        }


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

        }

    }
);


// ============================================================
// CANVAS
// ============================================================

if (
    formulaCanvas
) {

    formulaCanvas.addEventListener(
        "click",
        function (
            event
        ) {

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
// INITIAL
// ============================================================

renderFormula();