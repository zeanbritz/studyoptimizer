"use strict";

// No browser/library dependencies: exercise the shipped interaction controller
// with a deterministic clock, alongside browser checks of real rendering.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const source = fs.readFileSync(path.resolve(__dirname, "../../static/dashboard/js/today_garden.js"), "utf8");
const popupCode = source.slice(source.indexOf("    function cancelDismiss()"), source.indexOf("    // Exactly three tips"));

function fixture() {
    let now = 0, nextId = 0;
    const timers = new Map();
    const clock = {
        set(fn, ms) { const id = ++nextId; timers.set(id, {fn, due: now + ms}); return id; },
        clear(id) { timers.delete(id); },
        tick(ms) {
            const until = now + ms;
            for (;;) {
                const next = [...timers].filter(([, timer]) => timer.due <= until).sort((a, b) => a[1].due - b[1].due)[0];
                if (!next) break;
                timers.delete(next[0]); now = next[1].due; next[1].fn();
            }
            now = until;
        },
    };
    let document;
    class Node {
        constructor(parent = null) {
            this.parent = parent; this.listeners = new Map(); this.hidden = false;
            this.isConnected = true; this.attributes = new Map(); this.style = {};
            const classes = new Set();
            this.classList = {add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name)};
        }
        addEventListener(name, fn) { if (!this.listeners.has(name)) this.listeners.set(name, []); this.listeners.get(name).push(fn); }
        emit(name, properties = {}, bubble = false) {
            const event = {target: this, preventDefault() { this.defaultPrevented = true; }, ...properties};
            for (const fn of this.listeners.get(name) || []) fn(event);
            if (bubble && this.parent) this.parent.emit(name, event, true);
            return event;
        }
        contains(node) { return node === this || Boolean(node?.parent && this.contains(node.parent)); }
        setAttribute(name, value) { this.attributes.set(name, value); }
        removeAttribute(name) { this.attributes.delete(name); }
        getBoundingClientRect() { return {left: 100, top: 280, width: 116, height: 92, bottom: 372}; }
        focus() {
            if (document.activeElement === this) return;
            const old = document.activeElement;
            document.activeElement = this;
            old?.emit("focusout", {relatedTarget: this}, true);
            this.emit("focus"); this.emit("focusin", {}, true);
            document.emit("focusin", {target: this});
        }
    }
    document = new Node();
    const window = new Node(), popover = new Node();
    const button = new Node(popover), action = new Node(popover);
    const fields = new Map([["button", button], ["a", action], ["h4", new Node()], ["p", new Node()], [".garden-popover-kicker", new Node()]]);
    popover.querySelector = selector => fields.get(selector);
    popover.hidden = true;
    const context = vm.createContext({document, window, popover, innerWidth: 1200, innerHeight: 850,
        setTimeout: (fn, ms) => clock.set(fn, ms), clearTimeout: id => clock.clear(id),
        position: (node, x, y) => { node.style.left = x; node.style.top = y; },
    });
    vm.runInContext(`let selected=null, pointer='', restoringFocus=false, hoveredTrigger=null, popoverHovered=false, keyboardInteraction=false, dismissTimer;
        ${popupCode}
        this.controller={interactive,closeDetails,selected:()=>selected};`, context);
    function trigger(name = "leaf") {
        const node = new Node(); node.href = `/test/${name}/`;
        context.controller.interactive(node, {kicker: name, title: name, detail: "Details", action: "Open task"});
        return node;
    }
    return {trigger, document, window, popover, button, action, clock, controller: context.controller, Node,
        enter: node => node.emit("pointerenter", {pointerType: "mouse"}),
        leave: node => node.emit("pointerleave", {pointerType: "mouse"}),
        keyboard: () => document.emit("keydown", {key: "Tab"}),
    };
}

for (const type of ["leaf", "tree", "fruit"]) {
    test(`${type}: mouse exit dismisses at 200 ms, not immediately`, () => {
        const f = fixture(), node = f.trigger(type);
        f.enter(node); assert.equal(f.popover.hidden, false);
        f.leave(node); f.clock.tick(199); assert.equal(f.popover.hidden, false);
        f.clock.tick(1); assert.equal(f.popover.hidden, true);
        assert.equal(node.classList.contains("is-selected"), false);
    });
}

test("pointer can cross the gap into the pop-up and use its action", () => {
    const f = fixture(), node = f.trigger();
    f.enter(node); f.leave(node); f.clock.tick(150); f.enter(f.popover);
    f.clock.tick(500); assert.equal(f.popover.hidden, false);
    assert.equal(f.action.href, node.href);
    f.leave(f.popover); f.clock.tick(200); assert.equal(f.popover.hidden, true);
});

test("returning to the trigger cancels a pending dismissal", () => {
    const f = fixture(), node = f.trigger();
    f.enter(node); f.leave(node); f.clock.tick(175); f.enter(node);
    f.clock.tick(500); assert.equal(f.popover.hidden, false);
});

test("a new trigger replaces the previous pop-up without a stale timer closing it", () => {
    const f = fixture(), first = f.trigger("first"), second = f.trigger("second");
    f.enter(first); f.leave(first); f.clock.tick(100); f.enter(second);
    f.clock.tick(300);
    assert.equal(f.controller.selected(), second);
    assert.equal(first.classList.contains("is-selected"), false);
    assert.equal(f.action.href, second.href);
    assert.equal(f.popover.hidden, false);
});

test("keyboard focus within the trigger or pop-up keeps it open", () => {
    const f = fixture(), node = f.trigger();
    f.keyboard(); node.focus(); f.leave(node); f.clock.tick(400);
    assert.equal(f.popover.hidden, false);
    f.action.focus(); f.leave(f.popover); f.clock.tick(400);
    assert.equal(f.popover.hidden, false);
    new f.Node().focus(); f.clock.tick(199); assert.equal(f.popover.hidden, false);
    f.clock.tick(1); assert.equal(f.popover.hidden, true);
});

test("Tab reaches the pop-up; Shift-Tab returns without trapping focus", () => {
    const f = fixture(), node = f.trigger();
    f.keyboard(); node.focus(); node.emit("keydown", {key: "Tab", shiftKey: false});
    assert.equal(f.document.activeElement, f.button);
    f.button.emit("keydown", {key: "Tab", shiftKey: true});
    assert.equal(f.document.activeElement, node);
    assert.equal(node.emit("keydown", {key: "Tab", shiftKey: true}).defaultPrevented, undefined);
});

test("Escape closes, restores focus, and does not immediately reopen", () => {
    const f = fixture(), node = f.trigger();
    f.keyboard(); node.focus(); f.action.focus();
    f.document.emit("keydown", {key: "Escape"});
    assert.equal(f.popover.hidden, true);
    assert.equal(f.document.activeElement, node);
    f.clock.tick(300); assert.equal(f.popover.hidden, true);
});

test("scrolling a keyboard trigger into view does not dismiss its pop-up", () => {
    const f = fixture(), node = f.trigger();
    f.keyboard(); node.focus(); f.window.emit("scroll"); f.clock.tick(400);
    assert.equal(f.popover.hidden, false);
    assert.equal(f.controller.selected(), node);
});

test("mouse focus does not leave a hover pop-up stuck open", () => {
    const f = fixture(), node = f.trigger();
    f.enter(node); f.document.emit("pointerdown", {target: node}); node.focus();
    f.leave(node); f.clock.tick(200); assert.equal(f.popover.hidden, true);
});

test("touch tap stays open after finger release and closes on an outside tap", () => {
    const f = fixture(), node = f.trigger();
    f.document.emit("pointerdown", {target: node}); node.emit("pointerdown", {pointerType: "touch"});
    assert.equal(node.emit("click", {detail: 1}).defaultPrevented, true);
    node.emit("pointerleave", {pointerType: "touch"}); f.clock.tick(500);
    assert.equal(f.popover.hidden, false);
    f.document.emit("pointerdown", {target: new f.Node()});
    assert.equal(f.popover.hidden, true);
});

test("a mouse click keeps the native task link working", () => {
    const f = fixture(), node = f.trigger();
    f.enter(node); node.emit("pointerdown", {pointerType: "mouse"});
    assert.equal(node.emit("click", {detail: 1}).defaultPrevented, undefined);
});

test("all six leaf-tip directions remain vertical-dominant with natural variation", () => {
    const declaration = source.match(/    function leafAngle\(origin, index\) \{[\s\S]*?\n    \}/)[0];
    const angle = vm.runInNewContext(`(${declaration})`);
    for (const origin of ["top-left", "middle-left", "bottom-left", "bottom-right", "middle-right", "top-right"]) {
        for (let index = 0; index < 12; index++) {
            const radians = angle(origin, index) * Math.PI / 180;
            const tip = {x: Math.sin(radians), y: -Math.cos(radians)};
            assert.equal(Math.sign(tip.x), origin.endsWith("left") ? -1 : 1, origin);
            assert.equal(Math.sign(tip.y), origin.startsWith("bottom") ? -1 : 1, origin);
            assert.ok(Math.abs(tip.y) > Math.abs(tip.x) * 2, origin);
        }
    }
});
