(function () {
    "use strict";

    var form = document.getElementById("step-order-form");
    if (!form) return;

    var slots = Array.prototype.slice.call(document.querySelectorAll(".step-slot"));
    var bank = document.getElementById("available-steps");
    var hiddenOrder = document.getElementById("ordered-step-ids");
    var submitButton = document.getElementById("check-answer");
    var availableCount = document.getElementById("available-count");
    var status = document.getElementById("step-order-status");
    var selectedBlock = null;
    var draggedBlock = null;
    var suppressClick = false;
    var pointerState = null;

    function movableBlocks() {
        return Array.prototype.slice.call(document.querySelectorAll(".step-block.is-movable"));
    }

    function slotBlock(slot) {
        return slot.querySelector(".step-block");
    }

    function slotContent(slot) {
        return slot.querySelector(".slot-content");
    }

    function describe(block) {
        var label = block && block.querySelector(".step-text");
        return label ? label.textContent.trim() : "Step";
    }

    function announce(message) {
        status.textContent = message;
    }

    function clearTargets() {
        slots.forEach(function (slot) { slot.classList.remove("is-drop-target"); });
        bank.classList.remove("is-drop-target");
    }

    function clearSelection() {
        if (selectedBlock) {
            selectedBlock.classList.remove("is-selected");
            selectedBlock.setAttribute("aria-pressed", "false");
        }
        selectedBlock = null;
    }

    function selectBlock(block) {
        if (!block || !block.classList.contains("is-movable")) return;
        if (selectedBlock === block) {
            clearSelection();
            announce("Step selection cleared.");
            return;
        }
        clearSelection();
        selectedBlock = block;
        block.classList.add("is-selected");
        block.setAttribute("aria-pressed", "true");
        announce(describe(block) + " selected. Choose a numbered position.");
    }

    function sync() {
        var order = [];
        var complete = true;

        slots.forEach(function (slot) {
            var block = slotBlock(slot);
            slot.classList.toggle("is-filled", Boolean(block));
            if (block) {
                order.push(Number(block.dataset.stepId));
            } else {
                complete = false;
            }
        });

        hiddenOrder.value = complete ? JSON.stringify(order) : "";
        submitButton.disabled = !complete;
        var remaining = bank.querySelectorAll(".step-block.is-movable").length;
        if (availableCount) availableCount.textContent = String(remaining);
        if (complete) {
            announce("All steps are placed. You can check your answer.");
        } else if (!selectedBlock) {
            announce("Place " + remaining + " remaining step" + (remaining === 1 ? "" : "s") + ".");
        }
    }

    function moveToSlot(block, targetSlot) {
        if (!block || !targetSlot || targetSlot.classList.contains("is-locked")) return false;
        var sourceSlot = block.closest(".step-slot");
        if (sourceSlot === targetSlot) return true;

        var occupied = slotBlock(targetSlot);
        var targetContent = slotContent(targetSlot);
        var sourceContent = sourceSlot ? slotContent(sourceSlot) : null;

        targetContent.appendChild(block);
        if (occupied && occupied !== block) {
            if (sourceContent) {
                sourceContent.appendChild(occupied);
            } else {
                bank.appendChild(occupied);
            }
        }

        clearSelection();
        sync();
        announce(describe(block) + " moved to position " + (Number(targetSlot.dataset.position) + 1) + ".");
        block.focus({ preventScroll: true });
        return true;
    }

    function moveToBank(block) {
        if (!block || !block.classList.contains("is-movable")) return false;
        if (block.parentElement === bank) return true;
        bank.appendChild(block);
        clearSelection();
        sync();
        announce(describe(block) + " returned to available steps.");
        block.focus({ preventScroll: true });
        return true;
    }

    function targetAt(x, y) {
        var element = document.elementFromPoint(x, y);
        if (!element) return null;
        return element.closest(".step-slot:not(.is-locked), #available-steps");
    }

    function showTarget(target) {
        clearTargets();
        if (target) target.classList.add("is-drop-target");
    }

    movableBlocks().forEach(function (block) {
        block.setAttribute("aria-pressed", "false");

        block.addEventListener("dragstart", function (event) {
            draggedBlock = block;
            block.classList.add("is-dragging");
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", block.dataset.stepId);
        });

        block.addEventListener("dragend", function () {
            block.classList.remove("is-dragging");
            draggedBlock = null;
            clearTargets();
        });

        block.addEventListener("click", function (event) {
            event.stopPropagation();
            if (suppressClick) return;
            selectBlock(block);
        });

        block.addEventListener("keydown", function (event) {
            var key = event.key;
            if (key === " " || key === "Enter") {
                event.preventDefault();
                selectBlock(block);
                return;
            }
            if ((key === "Backspace" || key === "Delete") && block.closest(".step-slot")) {
                event.preventDefault();
                moveToBank(block);
                return;
            }
            if (key === "Escape") {
                clearSelection();
                announce("Step selection cleared.");
                return;
            }
            if (["ArrowUp", "ArrowLeft", "ArrowDown", "ArrowRight"].indexOf(key) === -1) return;

            event.preventDefault();
            var usableSlots = slots.filter(function (slot) { return !slot.classList.contains("is-locked"); });
            var currentSlot = block.closest(".step-slot");
            var currentIndex = usableSlots.indexOf(currentSlot);
            var backwards = key === "ArrowUp" || key === "ArrowLeft";
            var targetIndex;
            if (currentIndex === -1) {
                targetIndex = backwards ? usableSlots.length - 1 : 0;
            } else {
                targetIndex = Math.max(0, Math.min(usableSlots.length - 1, currentIndex + (backwards ? -1 : 1)));
            }
            moveToSlot(block, usableSlots[targetIndex]);
        });

        block.addEventListener("pointerdown", function (event) {
            if (event.pointerType === "mouse") return;
            pointerState = {
                id: event.pointerId,
                block: block,
                startX: event.clientX,
                startY: event.clientY,
                dragging: false,
                ghost: null
            };
            block.setPointerCapture(event.pointerId);
        });

        block.addEventListener("pointermove", function (event) {
            if (!pointerState || pointerState.id !== event.pointerId) return;
            var distance = Math.hypot(event.clientX - pointerState.startX, event.clientY - pointerState.startY);
            if (!pointerState.dragging && distance < 8) return;

            event.preventDefault();
            if (!pointerState.dragging) {
                pointerState.dragging = true;
                pointerState.ghost = block.cloneNode(true);
                pointerState.ghost.classList.add("drag-ghost");
                pointerState.ghost.removeAttribute("id");
                document.body.appendChild(pointerState.ghost);
                block.classList.add("is-dragging");
            }
            pointerState.ghost.style.left = (event.clientX + 14) + "px";
            pointerState.ghost.style.top = (event.clientY + 14) + "px";
            showTarget(targetAt(event.clientX, event.clientY));
        }, { passive: false });

        function finishPointer(event) {
            if (!pointerState || pointerState.id !== event.pointerId) return;
            var wasDragging = pointerState.dragging;
            var target = targetAt(event.clientX, event.clientY);
            if (pointerState.ghost) pointerState.ghost.remove();
            block.classList.remove("is-dragging");
            clearTargets();
            pointerState = null;

            if (wasDragging) {
                event.preventDefault();
                suppressClick = true;
                window.setTimeout(function () { suppressClick = false; }, 40);
                if (target === bank) moveToBank(block);
                else if (target) moveToSlot(block, target);
            }
        }

        block.addEventListener("pointerup", finishPointer);
        block.addEventListener("pointercancel", finishPointer);
    });

    slots.forEach(function (slot) {
        if (slot.classList.contains("is-locked")) return;
        slot.addEventListener("dragover", function (event) {
            if (!draggedBlock) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            showTarget(slot);
        });
        slot.addEventListener("drop", function (event) {
            event.preventDefault();
            clearTargets();
            moveToSlot(draggedBlock, slot);
        });
        slot.addEventListener("click", function () {
            if (selectedBlock) moveToSlot(selectedBlock, slot);
        });
        slot.addEventListener("keydown", function (event) {
            if ((event.key === "Enter" || event.key === " ") && selectedBlock) {
                event.preventDefault();
                moveToSlot(selectedBlock, slot);
            }
        });
    });

    bank.addEventListener("dragover", function (event) {
        if (!draggedBlock) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        showTarget(bank);
    });
    bank.addEventListener("drop", function (event) {
        event.preventDefault();
        clearTargets();
        moveToBank(draggedBlock);
    });
    bank.addEventListener("click", function () {
        if (selectedBlock) moveToBank(selectedBlock);
    });
    bank.addEventListener("keydown", function (event) {
        if ((event.key === "Enter" || event.key === " ") && selectedBlock) {
            event.preventDefault();
            moveToBank(selectedBlock);
        }
    });

    form.addEventListener("submit", function (event) {
        sync();
        if (!hiddenOrder.value) {
            event.preventDefault();
            announce("Place every available step before checking your answer.");
        }
    });

    sync();
}());
