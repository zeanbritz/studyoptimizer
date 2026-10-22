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

test("all six vines alternate left/right tips while retaining their vertical direction", () => {
    const declaration = source.match(/    function leafAngle\(origin, index\) \{[\s\S]*?\n    \}/)[0];
    const angle = vm.runInNewContext(`(${declaration})`);
    for (const origin of ["top-left", "middle-left", "bottom-left", "bottom-right", "middle-right", "top-right"]) {
        for (let index = 0; index < 12; index++) {
            const radians = angle(origin, index) * Math.PI / 180;
            const tip = {x: Math.sin(radians), y: -Math.cos(radians)};
            assert.equal(Math.sign(tip.x), index % 2 ? 1 : -1, origin);
            assert.equal(Math.sign(tip.y), origin.startsWith("bottom") ? -1 : 1, origin);
            assert.ok(Math.abs(tip.y) > Math.abs(tip.x) * 2, origin);
        }
    }
});

test("garden motion starts automatically without a control or saved preference", () => {
    const css=fs.readFileSync(path.resolve(__dirname,"../../static/dashboard/css/today_garden.css"),"utf8");
    const template=fs.readFileSync(path.resolve(__dirname,"../../templates/dashboard/partials/today_garden.html"),"utf8");
    assert.doesNotMatch(source,/motionPreference|motionIsEnabled|prefers-reduced-motion|studigarden\.garden-motion/);
    assert.doesNotMatch(template,/garden-motion|<select/);
    assert.doesNotMatch(css,/prefers-reduced-motion|data-motion/);
    for(const animation of ["tree-breeze","foliage-breeze","ivy-breeze"]) {
        assert.ok(css.includes(`animation: ${animation}`),`${animation} runs without opting in`);
    }
    assert.ok(css.includes(".garden-motion-paused"),"Hidden gardens still pause to save resources");
});

test("fruit shares the actual tree and canopy layers; ground fruit does not sway", () => {
    class Layer {
        constructor(tag,className) { this.tag=tag; this.className=className; this.children=[]; this.style={setProperty(){}}; }
        append(child) {
            if(child.parent)child.parent.children.splice(child.parent.children.indexOf(child),1);
            child.parent=this;
            this.children.push(child);
        }
    }
    const declarations=source.slice(source.indexOf("    function addTreeMotion("),source.indexOf("    function fruitArtwork("));
    const {addTreeMotion,attachFruit}=vm.runInNewContext(`${declarations}; ({addTreeMotion,attachFruit})`,{
        element:(tag,className)=>new Layer(tag,className)
    });
    const plant=new Layer("section","garden-tree"), marker=new Layer("span","garden-marker");
    plant.append(marker);
    const canopy=addTreeMotion(plant,{crownPivotY:90,branches:"branches",canopy:"foliage"});
    assert.equal(canopy.className,"garden-tree-canopy tree-crown");
    assert.equal(canopy.parent.className,"garden-tree-motion tree-sway");
    assert.equal(canopy.innerHTML,"foliage");
    assert.equal(canopy.parent.innerHTML,"branches");
    assert.equal(marker.parent,plant,"The marker stays outside both moving layers");
    const fruit=new Layer("a","garden-fruit");
    attachFruit(fruit,plant,canopy,false);
    assert.equal(fruit.parent,canopy);
    assert.equal(fruit.parent.parent.parent,plant,"Fruit and branches share one root pivot");
    attachFruit(fruit,plant,canopy,true);
    assert.equal(fruit.parent,plant,"Overdue fruit leaves both sway layers");
    assert.equal(canopy.children.includes(fruit),false);
    attachFruit(fruit,plant,canopy,false);
    assert.equal(fruit.parent,canopy,"A rescheduled date returns to the moving canopy");
    assert.equal(plant.children.includes(fruit),false);
});

test("all six growth stages keep soil separate from their moving branches and foliage", () => {
    const declarations=source.slice(source.indexOf("    function treeArtwork("),source.indexOf("    function addTreeMotion("));
    const attachedFruit=source.match(/    function attachedFruitPoint\(tree,index\) \{[\s\S]*?\n    \}/)[0];
    const artwork=vm.runInNewContext(`${attachedFruit}; ${declarations}; treeArtwork`);
    for(let stage=0;stage<6;stage++) {
        for(const count of [0,1,2,9]) {
            const tree={stage,id:stage+1,events:Array.from({length:count},(_,i)=>({id:i,status:"upcoming",completed:false}))};
            const parts=artwork(tree);
            assert.ok(parts.soil.includes("<ellipse"));
            assert.ok(parts.branches.includes("-bark"));
            assert.ok(parts.canopy.includes('class="tree-growth"'));
            assert.doesNotMatch(parts.soil,/tree-sway|tree-crown|tree-growth/);
            assert.doesNotMatch(parts.branches,/tree-sway|tree-crown|tree-growth/);
            assert.ok(parts.crownPivotY>=90&&parts.crownPivotY<=160);
            if(stage>0)assert.ok(parts.branches.includes("M100 188"),"The trunk remains anchored at the same root");
        }
    }
});

const fruitCode=source.slice(source.indexOf("    function fruitVisualState("),source.indexOf("    function treeGeometry("));
const {fruitVisualState,fruitArtwork}=vm.runInNewContext(`${fruitCode}; ({fruitVisualState,fruitArtwork})`);
const ripeSkins={"red-apple":"#c63d36","green-apple":"#82ab43","yellow-apple":"#e7b842",pear:"#b8bc58","red-pear":"#bf643b",peach:"#ee9d70"};

test("exam buds start tiny and green, then continuously grow into each assigned variety", () => {
    for(const [variety,ripeSkin] of Object.entries(ripeSkins)) {
        let lastScale=0;
        const colours=new Set();
        for(let step=0;step<=28;step++) {
            const ripeness=step/28;
            const visual=fruitVisualState({kind:"exam",status:"upcoming",fruit_ripeness:ripeness},variety);
            assert.ok(visual.scale>lastScale);
            assert.equal(visual.ripeness,ripeness);
            lastScale=visual.scale;
            colours.add(visual.skin);
            if(step===0) { assert.equal(visual.skin,"#5f962f"); assert.equal(visual.scale,.22); }
            if(step===28) { assert.equal(visual.skin,ripeSkin); assert.equal(visual.scale,1); }
        }
        assert.ok(colours.size>=20,`${variety} blends through intermediate colours instead of switching suddenly`);
    }
});

test("ripening changes colour and size without changing apple, pear, or peach silhouettes", () => {
    for(const variety of Object.keys(ripeSkins)) {
        const paths=ripeness=>[...fruitArtwork({id:1,kind:"exam",status:"upcoming",fruit_ripeness:ripeness},variety).matchAll(/<path d="([^"]+)"/g)].map(match=>match[1]);
        assert.deepEqual(paths(0),paths(.5));
        assert.deepEqual(paths(.5),paths(1));
    }
});

test("assessment fruit remains full-size with its existing ripe colour", () => {
    for(const [variety,ripeSkin] of Object.entries(ripeSkins)) {
        const visual=fruitVisualState({kind:"assessment",status:"upcoming",fruit_ripeness:0},variety);
        assert.equal(visual.scale,1);
        assert.equal(visual.skin,ripeSkin);
    }
});

test("overdue exams stay full-size and rotten, not tiny green buds", () => {
    for(const variety of Object.keys(ripeSkins)) {
        const event={id:2,kind:"exam",status:"overdue",fruit_ripeness:0};
        const visual=fruitVisualState(event,variety);
        assert.equal(visual.scale,1);
        assert.equal(visual.ripeness,1);
        const html=fruitArtwork(event,variety);
        assert.ok(html.includes(visual.decay));
        assert.ok(html.includes('fill="#302b20"'),"Rotten fruit retains its blemishes");
    }
});

test("missing or invalid cached ripeness stays safe and valid ages are clamped", () => {
    for(const value of [undefined,null,NaN,Infinity,"0.5"]) {
        assert.equal(fruitVisualState({kind:"exam",fruit_ripeness:value},"pear").scale,1);
    }
    assert.equal(fruitVisualState({kind:"exam",fruit_ripeness:-1},"pear").scale,.22);
    assert.equal(fruitVisualState({kind:"exam",fruit_ripeness:2},"pear").scale,1);
});

const geometryCode = source.slice(source.indexOf("    function leafAngle("), source.indexOf("    function smoothStem("));
const geometry = vm.runInNewContext(`const LEAF_SCALE=.83; const treeHeight=()=>352;
    ${geometryCode}; ({layout,vineLeafPoint})`);
const origins = ["top-left", "middle-left", "bottom-left", "bottom-right", "middle-right", "top-right"];
function stateWithLeaves(count) {
    return {trees: Array.from({length:6}, (_,i)=>({id:i})), categories:origins.map((origin,i)=>({
        origin,id:String(i),leaves:Array.from({length:count},(_,j)=>({id:`${i}-${j}`})),
    }))};
}
function rotate(x,y,radians) {
    return {x:x*Math.cos(radians)-y*Math.sin(radians),y:x*Math.sin(radians)+y*Math.cos(radians)};
}

test("leaf bases remain exactly attached during the full flutter on every vine and screen size", () => {
    for (const width of [220,238,284,319,320,390,659,660,900,1200]) {
        for (const count of [0,1,2,7,24]) {
            const plan=geometry.layout(stateWithLeaves(count),width);
            for (const vine of plan.vines) {
                assert.equal(vine.stem.length,count?count+2:2);
                vine.leaves.forEach((point,index)=>{
                    const side=index%2?1:-1;
                    assert.equal(point.side,side);
                    assert.equal(Math.sign(point.x-point.knot.x),side);
                    assert.equal(Math.sign(point.base.x-point.knot.x),side);
                    assert.equal(vine.stem[index+1],point.knot,"The petiole starts on the main stem");
                    for(const flutter of [-4,0,4.5]) {
                        // The SVG rotates at (60,87), then its wrapper rotates
                        // and scales at (60,46). The base must never drift.
                        const wind=rotate(0,0,flutter*Math.PI/180);
                        const oriented=rotate(wind.x,wind.y+41,point.angle*Math.PI/180);
                        assert.ok(Math.abs(point.base.x-(point.x+oriented.x*.83))<1e-9);
                        assert.ok(Math.abs(point.base.y-(point.y+oriented.y*.83))<1e-9);
                    }
                    assert.ok(point.x>=54&&point.x<=width-54,`Leaf clipped at width ${width}`);
                    assert.ok(point.y>90&&point.y<plan.height-90,"Leaves avoid end markers");
                });
            }
        }
    }
});

test("a long vine keeps separate clickable leaves instead of piling up subjects", () => {
    for (const width of [220,320,390,660,1200]) {
        const plan=geometry.layout(stateWithLeaves(24),width);
        const leaves=plan.vines.flatMap(vine=>vine.leaves);
        for(let i=0;i<leaves.length;i++) {
            for(let j=i+1;j<leaves.length;j++) {
                const a=leaves[i],b=leaves[j];
                assert.ok(Math.abs(a.x-b.x)>=120||Math.abs(a.y-b.y)>=92,
                    `Overlapping click targets at width ${width}: ${a.leaf.id} / ${b.leaf.id}`);
            }
        }
    }
});
