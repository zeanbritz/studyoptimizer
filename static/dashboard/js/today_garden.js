"use strict";

(() => {
    const source = document.getElementById("today-garden-data");
    const scene = document.getElementById("garden-scene");
    if (!source || !scene) return;
    let data;
    try { data = JSON.parse(source.textContent); } catch (_) { return; }
    const tabs = Array.from(document.querySelectorAll("[data-plan-view]"));
    const standard = document.getElementById("today-plan-standard");
    const garden = document.getElementById("today-plan-garden");
    const popover = document.getElementById("garden-popover");
    const status = document.getElementById("garden-sync-status");
    const storageKey = `studigarden.plan-view.${data.student}`;
    const snapshotKey = `studigarden.garden.${data.student}.${data.date}`;
    const svgNS = "http://www.w3.org/2000/svg";
    const LEAF_SCALE = .83;
    let selected = null, pointer = "", renderedWidth = 0, refreshInFlight = false;
    let restoringFocus = false;
    let hoveredTrigger = null, popoverHovered = false, keyboardInteraction = false, dismissTimer;
    let previous = readStorage(sessionStorage, snapshotKey, true);
    const fallenSeen = new Set(readStorage(sessionStorage, snapshotKey + ".fallen", true) || []);
    let activeView = "standard";
    let lastRefresh = Date.now();
    let resizeFrame;

    function readStorage(storage, key, json = false) {
        try { const value = storage.getItem(key); return json && value ? JSON.parse(value) : value; }
        catch (_) { return null; }
    }
    function saveStorage(storage, key, value) { try { storage.setItem(key, value); } catch (_) { /* Optional persistence. */ } }
    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }
    function svg(tag, attributes) {
        const node = document.createElementNS(svgNS, tag);
        Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
        return node;
    }
    function position(node, x, y) { node.style.left = `${Math.round(x)}px`; node.style.top = `${Math.round(y)}px`; }
    function statusLabel(event) {
        if (event.kind === "exam" && event.fruit_ripeness < 1 && event.status !== "overdue") return "Growing preview";
        return { completed: "Completed", overdue: "Overdue", today: "Due today", soon: "Coming up soon", upcoming: "Upcoming" }[event.status];
    }

    function setView(view, focus = false) {
        activeView = view === "garden" ? "garden" : "standard";
        tabs.forEach(tab => {
            const current = tab.dataset.planView === activeView;
            tab.setAttribute("aria-selected", String(current));
            tab.tabIndex = current ? 0 : -1;
            if (focus && current) tab.focus();
        });
        standard.hidden = activeView !== "standard";
        garden.hidden = activeView !== "garden";
        closeDetails();
        saveStorage(localStorage, storageKey, activeView);
        const currentURL=new URL(location.href);
        if(currentURL.searchParams.get("view")!==activeView) {
            currentURL.searchParams.set("view",activeView);
            history.replaceState(history.state,"",currentURL.pathname+currentURL.search+currentURL.hash);
        }
        if (activeView === "garden") { render(); refresh(); }
        updateMotion();
    }
    tabs.forEach(tab => {
        tab.addEventListener("click", () => setView(tab.dataset.planView));
        tab.addEventListener("keydown", event => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            setView(event.key === "Home" ? "standard" : event.key === "End" ? "garden" : activeView === "standard" ? "garden" : "standard", true);
        });
    });

    function cancelDismiss() {
        clearTimeout(dismissTimer);
        dismissTimer = undefined;
    }
    function focusWithinDetails() {
        return keyboardInteraction && selected && (
            selected.contains(document.activeElement) || popover.contains(document.activeElement)
        );
    }
    function scheduleDismiss() {
        cancelDismiss();
        dismissTimer = setTimeout(() => {
            dismissTimer = undefined;
            if (selected && hoveredTrigger !== selected && !popoverHovered && !focusWithinDetails()) closeDetails();
        }, 200);
    }
    function closeDetails(returnFocus = false) {
        cancelDismiss();
        const trigger = selected;
        selected = null;
        hoveredTrigger = null;
        popoverHovered = false;
        popover.hidden = true;
        if (trigger) {
            trigger.classList.remove("is-selected");
            trigger.removeAttribute("aria-describedby");
            if (returnFocus && trigger.isConnected) {
                restoringFocus = true;
                trigger.focus({ preventScroll: true });
                restoringFocus = false;
            }
        }
    }
    function showDetails(target, info) {
        cancelDismiss();
        if (selected && selected !== target) {
            selected.classList.remove("is-selected");
            selected.removeAttribute("aria-describedby");
        }
        selected = target;
        target.classList.add("is-selected");
        target.setAttribute("aria-describedby", "garden-popover");
        popover.querySelector(".garden-popover-kicker").textContent = info.kicker;
        popover.querySelector("h4").textContent = info.title;
        popover.querySelector("p").textContent = info.detail;
        const link = popover.querySelector("a");
        link.textContent = info.action;
        link.href = target.href;
        popover.hidden = false;
        positionDetails(target);
    }
    function positionDetails(target) {
        const rect = target.getBoundingClientRect();
        const popup = popover.getBoundingClientRect();
        const left = Math.max(12, Math.min(innerWidth - popup.width - 12, rect.left + rect.width / 2 - popup.width / 2));
        let top = rect.top - popup.height - 12;
        if (top < 72) top = Math.min(innerHeight - popup.height - 12, rect.bottom + 12);
        position(popover, left, Math.max(12, top));
    }
    function interactive(link, info) {
        link.addEventListener("pointerenter", event => {
            if (event.pointerType !== "mouse" && event.pointerType !== "pen") return;
            hoveredTrigger = link;
            showDetails(link, info);
        });
        link.addEventListener("pointerleave", event => {
            if (event.pointerType !== "mouse" && event.pointerType !== "pen") return;
            if (hoveredTrigger === link) hoveredTrigger = null;
            if (selected === link) scheduleDismiss();
        });
        link.addEventListener("focus", () => { if (!restoringFocus) showDetails(link, info); });
        link.addEventListener("focusout", scheduleDismiss);
        link.addEventListener("keydown", event => {
            if (event.key === "Tab" && !event.shiftKey && selected === link && !popover.hidden) {
                event.preventDefault();
                popover.querySelector("button").focus();
            }
        });
        link.addEventListener("pointerdown", event => { pointer = event.pointerType; });
        link.addEventListener("click", event => {
            if (event.detail && pointer !== "mouse") {
                // Touch users can inspect details and use the explicit action in the popover.
                event.preventDefault();
                showDetails(link, info);
            }
        });
    }
    popover.addEventListener("pointerenter", event => {
        if (event.pointerType !== "mouse" && event.pointerType !== "pen") return;
        popoverHovered = true;
        cancelDismiss();
    });
    popover.addEventListener("pointerleave", event => {
        if (event.pointerType !== "mouse" && event.pointerType !== "pen") return;
        popoverHovered = false;
        scheduleDismiss();
    });
    popover.addEventListener("focusin", cancelDismiss);
    popover.addEventListener("focusout", scheduleDismiss);
    popover.querySelector("button").addEventListener("keydown", event => {
        if (event.key === "Tab" && event.shiftKey && selected) {
            event.preventDefault();
            selected.focus();
        }
    });
    popover.querySelector("button").addEventListener("click", () => closeDetails(true));
    document.addEventListener("pointerdown", event => {
        keyboardInteraction = false;
        if (selected && !popover.contains(event.target) && !selected.contains(event.target)) closeDetails();
    }, true);
    document.addEventListener("keydown", event => {
        keyboardInteraction = true;
        if (event.key === "Escape" && !popover.hidden) { event.preventDefault(); closeDetails(true); }
    }, true);
    document.addEventListener("focusin", event => {
        if (popover.hidden) return;
        if (popover.contains(event.target) || selected?.contains(event.target)) cancelDismiss();
        else scheduleDismiss();
    });
    // Keyboard focus can scroll its trigger into view. Keep the pop-up anchored
    // instead of closing it during that automatic scroll.
    window.addEventListener("scroll", () => { if (selected) positionDetails(selected); }, { passive: true });

    // Exactly three tips, with two deep sinuses and a softly rounded base.
    const ivyShape = "M60 87C46 78 33 79 25 68L7 36L39 44L60 4L81 44L113 36L95 68C87 79 74 78 60 87Z";

    function leafArtwork(categoryIndex, id) {
        const gradient = "ivy-" + id;
        return `<svg viewBox="0 0 120 92" aria-hidden="true"><defs><linearGradient id="${gradient}" x1="0" y1="0" x2=".8" y2="1"><stop stop-color="#699349"/><stop offset=".45" stop-color="#3d743b"/><stop offset="1" stop-color="#234e32"/></linearGradient></defs><path d="${ivyShape}" fill="url(#${gradient})" stroke="#adc17c" stroke-width="1.1"/><path d="M60 84L60 14M60 70Q38 54 16 42M60 70Q82 54 104 42M60 56L49 45M60 56L71 45M43 58L32 60M77 58L88 60" fill="none" stroke="#b1c786" stroke-width="1.2" opacity=".55"/><path d="M60 17L62 67L60 83" fill="none" stroke="#e0dfa1" opacity=".25"/></svg>`;
    }

    function treeArtwork(tree) {
        const stage = tree.stage;
        const id = "tree-" + tree.id;
        const crowns = [null, null, {cy:133,rx:31,ry:25}, {cy:106,rx:45,ry:34}, {cy:85,rx:56,ry:41}, {cy:70,rx:65,ry:46}];
        const crown = crowns[stage];
        const trunkWidth = [0,2.8,4.5,7.5,10,13][stage];
        let branches = "", foliage = "";
        if(stage===0 && tree.events.some(event=>event.status!=="overdue" && !event.completed)) {
            // A small fruit-bearing twig keeps dates rooted even before any pages
            // are summarized; the progress-controlled crown is still ungrown.
            branches='<path d="M100 188Q96 174 100 158M99 173Q87 151 78 131M100 181Q112 175 124 167" fill="none" stroke="#80613c" stroke-width="3" stroke-linecap="round"/>';
            foliage='<path d="M80 157Q68 151 71 142Q83 141 87 152ZM119 174Q128 160 136 167Q134 177 119 174Z" fill="#547d39" stroke="#95ac65" stroke-width=".8"/>';
        }
        if (stage > 0) {
            const top = crown ? crown.cy + 8 : 156;
            branches = `<path d="M100 188Q96 165 100 ${top}" fill="none" stroke="url(#${id}-bark)" stroke-width="${trunkWidth}" stroke-linecap="round"/><path d="M98 184Q102 164 102 ${top+12}" stroke="#c19a61" stroke-width="${Math.max(1,trunkWidth*.18)}" fill="none" opacity=".65"/>`;
            if (crown) {
                branches += `<path d="M99 158Q87 ${crown.cy+36} 74 ${crown.cy+10}M101 148Q119 ${crown.cy+26} 133 ${crown.cy+6}" fill="none" stroke="#755137" stroke-width="${trunkWidth*.58}" stroke-linecap="round"/>`;
                const lobes = [[-.55,-.12,.58,.75],[.05,-.47,.67,.72],[.59,-.05,.56,.78],[.4,.44,.58,.6],[-.33,.48,.68,.62],[.03,.02,.74,.88]];
                const shades = ["#406d33","#6b963e","#4c7d32","#2e5a31","#365f2d","#5b8736"];
                foliage = `<ellipse cx="103" cy="${crown.cy+11}" rx="${crown.rx*.94}" ry="${crown.ry*.92}" fill="#233f29" opacity=".65"/>`;
                lobes.forEach(([dx,dy,rx,ry],i) => {
                    const x = 100 + dx*crown.rx, y = crown.cy + dy*crown.ry;
                    foliage += `<ellipse cx="${x}" cy="${y}" rx="${rx*crown.rx}" ry="${ry*crown.ry}" fill="${shades[i]}"/><path d="M${x-rx*crown.rx*.55} ${y-3}q${rx*crown.rx*.3} ${-ry*crown.ry*.8} ${rx*crown.rx} ${-ry*crown.ry*.38}" fill="none" stroke="#b3c970" stroke-width="3" opacity=".22"/>`;
                });
                for (let i=0; i<25; i++) {
                    const angle=i*2.39996, radius=Math.sqrt(i/25);
                    const x=100+Math.cos(angle)*crown.rx*.83*radius;
                    const y=crown.cy+Math.sin(angle)*crown.ry*.8*radius;
                    foliage += `<path d="M${x-6} ${y}Q${x-2} ${y-7} ${x+7} ${y-2}Q${x+2} ${y+4} ${x-6} ${y}Z" fill="${i%3?'#a3ba5b':'#234c2d'}" opacity=".48" transform="rotate(${i*31} ${x} ${y})"/>`;
                }
            } else {
                foliage = '<path d="M100 164C77 166 69 149 77 139C94 138 102 149 100 164Z" fill="#7ba849" stroke="#b7ca7b"/><path d="M101 159C102 138 121 127 132 138C129 154 117 161 101 159Z" fill="#4a823c" stroke="#98b366"/><path d="M99 162L80 143M103 157L127 138" fill="none" stroke="#c7d590" stroke-width="1.2"/>';
            }
        }
        const mound = stage===0
            ? '<path d="M65 191Q80 169 103 174Q124 174 139 191Q111 208 65 191Z" fill="#59402a" stroke="#ba8e5c"/><ellipse cx="101" cy="183" rx="7" ry="4" transform="rotate(-25 101 183)" fill="#ddba80"/><path d="M78 198Q102 204 126 197" fill="none" stroke="#d0a46e" opacity=".55"/>'
            : '<ellipse cx="100" cy="190" rx="25" ry="9" fill="#412d21" stroke="#a17b50"/>';
        // Extra dates occupy leafy, low boughs, not a row of floating fruit.
        // These are one shared woody branch per cluster, never fruit tethers.
        const attachedCount=tree.events.filter(event=>!event.completed&&event.status!=="overdue").length;
        for(let row=0;row<Math.ceil(Math.max(0,attachedCount-6)/3);row++) {
            const y=attachedFruitPoint(tree,6+row*3).y;
            branches+=`<path d="M100 164Q112 ${y-19} 100 ${y-11}M100 ${y-11}Q76 ${y-21} 48 ${y-14}M100 ${y-11}Q127 ${y-22} 153 ${y-13}" fill="none" stroke="#79583a" stroke-width="5" stroke-linecap="round"/>`;
            for(let col=0;col<Math.min(3,attachedCount-6-row*3);col++) {
                const x=50+col*50;
                foliage+=`<ellipse cx="${x}" cy="${y-13}" rx="29" ry="18" fill="#416e36"/><path d="M${x-21} ${y-15}Q${x} ${y-35} ${x+21} ${y-15}" fill="none" stroke="#93ac5d" stroke-width="3" opacity=".5"/>`;
            }
        }
        // Separate static soil from the moving artwork. HTML motion layers let
        // native fruit links share the very same transforms as the branches.
        const start=`<svg class="garden-tree-art" viewBox="0 0 200 240" aria-hidden="true" data-growth-stage="${stage}">`;
        return {
            crownPivotY:crown?crown.cy+20:160,
            soil:`${start}<defs><radialGradient id="${id}-shade"><stop stop-color="#2e281c" stop-opacity=".5"/><stop offset="1" stop-color="#2e281c" stop-opacity="0"/></radialGradient></defs><ellipse cx="115" cy="197" rx="${stage>1?55:36}" ry="18" transform="rotate(-9 115 197)" fill="url(#${id}-shade)"/><ellipse cx="100" cy="190" rx="44" ry="16" transform="rotate(-8 100 190)" fill="#a17b49" opacity=".28"/>${mound}</svg>`,
            branches:`${start}<defs><linearGradient id="${id}-bark"><stop stop-color="#593e2a"/><stop offset=".55" stop-color="#ab8051"/><stop offset="1" stop-color="#62452d"/></linearGradient></defs>${branches}</svg>`,
            canopy:`${start}<g class="tree-growth">${foliage}</g></svg>`
        };
    }

    function addTreeMotion(plant, artwork) {
        const motion=element("div","garden-tree-motion tree-sway");
        motion.style.setProperty("--crown-pivot-y",`${artwork.crownPivotY}px`);
        motion.innerHTML=artwork.branches;
        const canopy=element("div","garden-tree-canopy tree-crown");
        canopy.innerHTML=artwork.canopy;
        motion.append(canopy);
        plant.append(motion);
        return canopy;
    }

    function attachFruit(fruit, plant, canopy, fallen) {
        // Attached dates inherit both tree and foliage motion. Ground fruit
        // must remain outside those layers, including after an event is moved.
        (fallen?plant:canopy).append(fruit);
    }

    function fruitVisualState(event, variety) {
        const palettes = {
            "red-apple": ["#ee8872", "#c63d36", "#752e29", "#724b3a"],
            "green-apple": ["#d7e892", "#82ab43", "#4b6d29", "#59613b"],
            "yellow-apple": ["#fff0a2", "#e7b842", "#9e7329", "#807044"],
            "pear": ["#f2e299", "#b8bc58", "#75833b", "#6c7041"],
            "red-pear": ["#efb16e", "#bf643b", "#7e3e2c", "#75513d"],
            "peach": ["#ffe1a6", "#ee9d70", "#c56656", "#83644e"]
        };
        const ripe = palettes[variety] || palettes["red-apple"];
        // Dates use Django's same local study day as Today's Plan.
        // Never use time since page load: return visits must show the right age.
        const ripeness = event.kind === "exam" && event.status !== "overdue" && Number.isFinite(event.fruit_ripeness)
            ? Math.max(0, Math.min(1, event.fruit_ripeness)) : 1;
        const blend = (green, colour) => "#" + [1,3,5].map(offset => {
            const from = parseInt(green.slice(offset,offset+2),16), to = parseInt(colour.slice(offset,offset+2),16);
            return Math.round(from+(to-from)*ripeness).toString(16).padStart(2,"0");
        }).join("");
        return {
            ripeness, scale:.22+.78*ripeness,
            light:blend("#a8ce76",ripe[0]), skin:blend("#5f962f",ripe[1]), edge:blend("#365f2e",ripe[2]),
            decay:ripe[3], cleft:blend("#4e7134","#cf7b66")
        };
    }

    function fruitArtwork(event, variety) {
        const rotten = event.status === "overdue", pear = variety.includes("pear"), peach = variety === "peach";
        const {light,skin,edge,decay,cleft:cleftColour} = fruitVisualState(event,variety);
        const shape = pear
            ? "M20 9C13 9 15 19 10 23C1 31 7 41 20 41C34 41 39 31 30 23C25 18 27 9 20 9Z"
            : peach
            ? "M20 14C10 7 2 16 4 28C5 38 14 43 20 40C27 43 36 37 37 27C39 15 29 8 20 14Z"
            : "M20 13C5 3 0 23 7 34C12 43 17 40 20 39C25 43 33 39 36 28C40 14 30 6 20 13Z";
        const gradient = `fruit-${event.id}`;
        const blemishes = rotten
            ? '<ellipse cx="13" cy="27" rx="5" ry="4" fill="#302b20"/><ellipse cx="25" cy="33" rx="6" ry="4" fill="#403126"/><circle cx="24" cy="24" r="2.5" fill="#8a8b55"/><path d="M9 30L15 32L18 28M23 16L20 23L22 27M30 35L25 31" stroke="#332c21" stroke-width="1" fill="none"/>'
            : '<path d="M11 20Q7 25 11 29" stroke="#fff5d6" opacity=".65" stroke-width="2.5" stroke-linecap="round" fill="none"/>';
        const cleft = peach ? `<path d="M21 15Q27 26 20 39" fill="none" stroke="${rotten?'#4c3e31':cleftColour}" opacity=".65"/>` : "";
        return `<svg viewBox="0 0 40 44" aria-hidden="true"><defs><radialGradient id="${gradient}" cx=".3" cy=".3" r=".85"><stop stop-color="${rotten?decay:light}"/><stop offset=".65" stop-color="${rotten?decay:skin}"/><stop offset="1" stop-color="${rotten?'#493d2b':edge}"/></radialGradient></defs><path d="M20 13Q19 8 22 5" stroke="${rotten?'#51432f':'#674f2d'}" stroke-width="2.5" fill="none"/><path d="M21 10Q27 4 30 8Q28 12 21 10" fill="${rotten?'#65633e':'#4c792f'}"/><path d="${shape}" fill="url(#${gradient})" stroke="${rotten?'#483b29':edge}" stroke-width="1.1"/>${cleft}${blemishes}</svg>`;
    }

    function treeGeometry(tree) {
        const attached = tree.events.filter(event => !event.completed && event.status!=="overdue");
        const fallen = tree.events.filter(event => !event.completed && event.status==="overdue");
        const extraRows = Math.max(0,Math.ceil((attached.length-6)/3));
        const markerTop = 230 + extraRows*50;
        return {attached,fallen,markerTop,height:markerTop+70+Math.ceil(fallen.length/3)*52};
    }
    function attachedFruitPoint(tree,index) {
        const centerY=[155,149,133,106,85,70][tree.stage];
        if(index>=6) return {x:50+((index-6)%3)*50,y:208+Math.floor((index-6)/3)*50};
        // Stagger the fruit within the crown, rather than hanging it on strings.
        const count=tree.events.filter(event=>!event.completed&&event.status!=="overdue").length;
        if(count===1) return {x:100,y:centerY+9};
        const offsets=[[-23,-10],[23,26],[-23,44],[23,-28],[-65,8],[65,-10]];
        return {x:100+offsets[index][0],y:centerY+offsets[index][1]};
    }
    function treeHeight(tree) { return treeGeometry(tree).height; }

    function leafAngle(origin, index) {
        const side = index % 2 ? 1 : -1;
        const direction = origin.startsWith("bottom") ? 22 : 158;
        return side * direction + ((index % 3) - 1) * 2;
    }

    function vineLeafPoint(origin, index, stemX, y, gap, leaf) {
        // Alternate around one continuous stem. Keep the petiole at the leaf's
        // exact SVG base (60,87), after its rotation/scale about (60,46).
        const side = index % 2 ? 1 : -1;
        const x = stemX + side * gap;
        const angle = leafAngle(origin, index), radians = angle * Math.PI / 180;
        const base = {x:x-Math.sin(radians)*41*LEAF_SCALE, y:y+Math.cos(radians)*41*LEAF_SCALE};
        const knot = {x:stemX, y:base.y+(origin.startsWith("bottom")?15:-15)};
        return {leaf,x,y,angle,base,knot,side};
    }

    function layout(state,width) {
        const mobile=width<660, narrow=width<320;
        const side=mobile?width/2:Math.min(230,Math.max(172,width*.25));
        const pairs=[[0,5],[1,4],[2,3]];
        const leafSpacing=narrow?248:122;
        let heights=pairs.map(pair=>Math.max(220,...pair.map(i=>(narrow?250:130)+Math.max(1,state.categories[i].leaves.length)*leafSpacing)));
        const maxTreeHeight=Math.max(300,...state.trees.map(treeHeight));
        const trees=[],slots=[],bandTops=[];
        let height=0;
        if(mobile) {
            const split=Math.ceil(state.trees.length/2);
            for(let band=0;band<3;band++) {
                bandTops.push(height);height+=heights[band];
                const count=band===0?split:band===1?state.trees.length-split:0;
                for(let i=0;i<count;i++) {
                    slots.push({x:width/2-100+(width>240?(i%2?7:-7):0),y:height+12});
                    height+=maxTreeHeight+36;
                }
                if(band===0&&!state.trees.length)height+=230;
            }
        } else {
            const centerWidth=width-side*2;
            const columns=Math.max(1,Math.floor(centerWidth/212));
            const rows=Math.ceil(state.trees.length/columns);
            const rowHeight=maxTreeHeight+42;
            height=Math.max(940,rows*rowHeight+160,heights.reduce((a,b)=>a+b,0));
            const extra=(height-heights.reduce((a,b)=>a+b,0))/3;
            heights=heights.map(h=>h+extra);
            bandTops.push(0,heights[0],heights[0]+heights[1]);
            for(let row=0;row<rows;row++) {
                const rowCount=Math.min(columns,state.trees.length-row*columns);
                for(let col=0;col<rowCount;col++) {
                    slots.push({
                        x:width/2+(col-(rowCount-1)/2)*212-100+(row%2?5:-5),
                        y:height/2+(row-(rows-1)/2)*rowHeight-190+(col%2?9:-9)
                    });
                }
            }
        }
        // Fill the central planting positions first; growth never moves a root.
        slots.sort((a,b)=>Math.hypot((a.x+100-width/2)*1.3,a.y+190-height/2)-Math.hypot((b.x+100-width/2)*1.3,b.y+190-height/2));
        state.trees.forEach((tree,i)=>trees.push({tree,...slots[i],h:treeHeight(tree)}));
        const vines=state.categories.map((category,i)=>{
            const band=i<3?i:5-i,right=i>=3,bottom=band===2;
            const top=bandTops[band],h=heights[band],offset=narrow&&right?74:0;
            const origin={x:right?width-14:14,y:bottom?top+h-22-offset:top+28+offset};
            const label={x:right?width-(mobile?138:150):9,y:bottom?top+h-82-offset:top+12+offset};
            const leaves=category.leaves.map((leaf,j)=>{
                const lane=narrow?width-24:side;
                const gap=Math.min(48,lane/2-62);
                const center=narrow?width/2+(right?12:-12):right?width-side/2:side/2;
                const stemX=center+Math.sin((j+1)*.9)*4;
                const depth=(narrow?230:144)+j*leafSpacing+(narrow&&right?124:0);
                const y=bottom?top+h-depth:top+depth;
                return vineLeafPoint(category.origin,j,stemX,y,gap,leaf);
            });
            const tail=leaves.length
                ? {x:leaves[leaves.length-1].knot.x+(right?-19:19),y:leaves[leaves.length-1].knot.y+(bottom?-24:24)}
                : {x:origin.x+(right?-42:42),y:origin.y+(bottom?-60:65)};
            return {category,i,origin,label,leaves,stem:[origin,...leaves.map(p=>p.knot),tail]};
        });
        return {height,trees,vines,emptyTop:mobile?heights[0]+20:height/2-80};
    }

    function smoothStem(points) {
        let path=`M${points[0].x} ${points[0].y}`;
        for(let i=1;i<points.length;i++) {
            const p0=points[Math.max(0,i-2)],p1=points[i-1],p2=points[i],p3=points[Math.min(points.length-1,i+1)];
            path+=`C${p1.x+(p2.x-p0.x)/6} ${p1.y+(p2.y-p0.y)/6},${p2.x-(p3.x-p1.x)/6} ${p2.y-(p3.y-p1.y)/6},${p2.x} ${p2.y}`;
        }
        return path;
    }
    function addThorns(stem,layer) {
        const length=stem.getTotalLength();
        for(let distance=24,i=0;distance<length-12;distance+=43,i++) {
            const p=stem.getPointAtLength(distance),before=stem.getPointAtLength(distance-2),after=stem.getPointAtLength(distance+2);
            const dx=after.x-before.x,dy=after.y-before.y,magnitude=Math.hypot(dx,dy)||1;
            const tx=dx/magnitude,ty=dy/magnitude,side=i%2?1:-1;
            layer.append(svg("path",{
                class:"garden-thorn",
                d:`M${p.x-tx*3} ${p.y-ty*3}L${p.x-ty*7*side+tx*2} ${p.y+tx*7*side+ty*2}L${p.x+tx*3} ${p.y+ty*3}Z`
            }));
        }
    }

    function drawLeaf(point, category, index, completed=false) {
        const link=element("a", `garden-leaf${completed?' garden-completed-leaf':''}`);
        link.href=point.leaf.url;
        link.dataset.leafId=point.leaf.id;
        link.dataset.stemSide=point.side<0?"left":"right";
        link.style.setProperty("--leaf-angle", `${point.angle}deg`);
        link.style.setProperty("--leaf-scale",LEAF_SCALE);
        const seed=point.leaf.subject_id+index*7;
        link.style.setProperty("--breeze-delay", `${-(seed%19)*.73}s`);
        link.style.setProperty("--breeze-duration", `${5.8+(seed%7)*.47}s`);
        // No integer rounding or SVG letterboxing: the stalk and leaf share
        // precisely the same base even while the blade flutters around it.
        link.style.left=`${point.x-60}px`;
        link.style.top=`${point.y-46}px`;
        const visual=element("span","garden-leaf-visual");
        visual.setAttribute("aria-hidden","true");
        visual.innerHTML=leafArtwork(index,point.leaf.id+(completed?'-done':''));
        link.append(visual,element("span","garden-leaf-title",point.leaf.subject));
        const itemWord=point.leaf.count===1?'item':'items';
        link.setAttribute("aria-label",`${point.leaf.subject}, ${category.label}, ${point.leaf.count} ${itemWord} to review`);
        if (!completed) interactive(link,{kicker:category.label,title:point.leaf.subject,detail:`${point.leaf.count} ${itemWord} to review today.`,action:category.id==='notes'?'Study notes':'Start review'});
        else { link.tabIndex=-1; link.setAttribute("aria-hidden","true"); setTimeout(()=>link.remove(),900); }
        return link;
    }

    function render() {
        const width=scene.clientWidth;
        if(!width||activeView!=="garden")return;
        renderedWidth=width;
        closeDetails();
        const plan=layout(data,width);
        const old=previous&&previous.date===data.date?layout(previous,width):null;
        scene.replaceChildren();
        scene.style.minHeight="0";
        scene.style.height=`${plan.height}px`;
        // The soil's declared height includes its border. Use the real inner
        // viewport, or SVG "meet" scaling pulls stalks away from HTML leaves.
        const stems=svg("svg",{class:"garden-stems",viewBox:`0 0 ${width} ${scene.clientHeight}`,preserveAspectRatio:"none","aria-hidden":"true"});
        scene.append(stems);
        let completed=0;
        plan.vines.forEach(vine=>{
            const group=element("section","garden-vine");
            group.setAttribute("aria-label",`${vine.category.label}, ${vine.leaves.length} subject${vine.leaves.length===1?"":"s"} to review`);
            const marker=element("div","garden-vine-label garden-marker");
            position(marker,vine.label.x,vine.label.y);
            marker.append(element("strong","",vine.category.label));
            group.append(marker);
            const mainStem=svg("path",{d:smoothStem(vine.stem),class:"garden-main-stem","data-category":vine.category.id});
            const stemGroup=svg("g",{class:"garden-vine-stem"});
            stems.append(stemGroup);
            stemGroup.append(mainStem);
            addThorns(mainStem,stemGroup);
            vine.leaves.forEach(point=>{
                stemGroup.append(svg("path",{
                    class:"garden-leaf-stalk",
                    "data-leaf-id":point.leaf.id,
                    d:`M${point.knot.x} ${point.knot.y}Q${(point.base.x+point.knot.x)/2} ${point.knot.y} ${point.base.x} ${point.base.y}`
                }));
                group.append(drawLeaf(point,vine.category,vine.i));
            });
            if(old) {
                const prior=old.vines.find(v=>v.category.id===vine.category.id);
                prior?.leaves.forEach(point=>{
                    if(!vine.category.leaves.some(leaf=>leaf.id===point.leaf.id)) {
                        completed++;
                        group.append(drawLeaf(point,vine.category,vine.i,true));
                    }
                });
            }
            scene.append(group);
        });
        const currentOverdue=new Set();
        plan.trees.forEach(({tree,x,y,h})=>{
            const geometry=treeGeometry(tree);
            const plant=element("section","garden-tree");
            plant.dataset.subjectId=tree.id;
            plant.dataset.rootX=Math.round(x+100);
            plant.dataset.rootY=Math.round(y+190);
            plant.setAttribute("aria-label",`${tree.subject} study tree`);
            position(plant,x,y);
            plant.style.height=`${h}px`;
            plant.style.setProperty("--breeze-delay",`${-(tree.id%7)*.9}s`);
            plant.style.setProperty("--breeze-duration",`${6.8+(tree.id%5)*.63}s`);
            const link=element("a","garden-tree-link");
            link.href=tree.url;
            const artwork=treeArtwork(tree);
            link.innerHTML=artwork.soil;
            const marker=element("span","garden-tree-label garden-marker");
            marker.style.top=`${geometry.markerTop}px`;
            marker.append(element("strong","",tree.subject));
            link.append(marker);
            const detail=tree.progress===null
                ?"No textbook page total yet. Add a textbook to watch this tree grow."
                :`${tree.summarized_pages} of ${tree.total_pages} pages summarized (${tree.progress}%).${tree.today_pages?`\nToday's study target: ${tree.today_pages} page${tree.today_pages===1?"":"s"}.`:""}`;
            link.setAttribute("aria-label",`${tree.subject}. ${detail}`);
            interactive(link,{kicker:"Study · Summarizing progress",title:tree.subject,detail,action:"Open Study"});
            plant.append(link);
            const canopy=addTreeMotion(plant,artwork);
            const prior=previous?.trees.find(t=>t.id===tree.id);
            if(prior&&prior.progress!==tree.progress)canopy.querySelector(".tree-growth").classList.add("garden-growth");
            if(tree.stage>=2) {
                // One tiny oval (not an ivy task leaf), reused by a sparse CSS cycle.
                // No timers, hit targets, task data, or accumulating ground nodes.
                const drift=element("span","garden-drift-leaf");
                drift.setAttribute("aria-hidden","true");
                const crownY=[155,149,133,106,85,70][tree.stage];
                position(drift,86+(tree.id%4)*9,crownY);
                drift.style.setProperty("--drift-distance",`${180-crownY}px`);
                drift.style.setProperty("--drift-duration",`${27+(tree.id%7)*2.1}s`);
                drift.style.setProperty("--drift-delay",`${2+(tree.id%11)*.55}s`);
                drift.innerHTML='<svg viewBox="0 0 18 10" focusable="false"><path d="M1 8Q3-1 17 2Q13 12 1 8Z" fill="#c6a45c"/><path d="M2 8L14 3" stroke="#796f3e" stroke-width=".7"/></svg>';
                plant.append(drift);
            }
            if(geometry.fallen.length) {
                const ground=element("div","garden-fallen-bed");
                position(ground,10,geometry.markerTop+67);
                ground.style.height=`${Math.ceil(geometry.fallen.length/3)*52}px`;
                ground.setAttribute("aria-hidden","true");
                plant.append(ground);
            }
            const drawFruit=(event,index,fallen)=>{
                const point=fallen
                    ?{x:50+(index%3)*50,y:geometry.markerTop+90+Math.floor(index/3)*52}
                    :attachedFruitPoint(tree,index);
                const fruit=element("a",`garden-fruit${fallen?" garden-fruit-fallen":""}`);
                fruit.href=event.url;
                fruit.dataset.status=event.status;
                fruit.dataset.eventId=event.id;
                fruit.dataset.placement=fallen?"ground":"tree";
                fruit.dataset.variety=tree.fruit || "red-apple";
                fruit.dataset.kind=event.kind;
                position(fruit,point.x-22,point.y-22);
                const appearance=fruitVisualState(event,fruit.dataset.variety);
                fruit.dataset.ripeness=appearance.ripeness;
                fruit.dataset.phase=fallen?"rotten":appearance.ripeness<1?"growing":"ripe";
                fruit.style.setProperty("--fruit-scale",appearance.scale);
                // Keep a 44px native link even when the visible fruit is a tiny bud.
                const visual=element("span","garden-fruit-visual");
                visual.innerHTML=fruitArtwork(event,fruit.dataset.variety);
                visual.append(element("span","garden-fruit-kind",event.kind==="exam"?"E":"A"));
                fruit.append(visual);
                const priorEvent=prior?.events.find(e=>e.id===event.id);
                if(fallen) {
                    currentOverdue.add(event.id);
                    if(!fallenSeen.has(event.id)) {
                        const priorIndex=prior?treeGeometry(prior).attached.findIndex(e=>e.id===event.id):-1;
                        const from=attachedFruitPoint(tree,Math.max(0,priorIndex));
                        fruit.style.setProperty("--fruit-from-x",`${from.x-point.x}px`);
                        fruit.style.setProperty("--fruit-from-y",`${from.y-point.y}px`);
                        fruit.classList.add("garden-fruit-falling");
                    }
                    fallenSeen.add(event.id);
                } else {
                    if(priorEvent?.status==="overdue") {
                        const oldGeometry=treeGeometry(prior);
                        const groundIndex=Math.max(0,oldGeometry.fallen.findIndex(e=>e.id===event.id));
                        fruit.style.setProperty("--fruit-from-x",`${50+(groundIndex%3)*50-point.x}px`);
                        fruit.style.setProperty("--fruit-from-y",`${oldGeometry.markerTop+90+Math.floor(groundIndex/3)*52-point.y}px`);
                        fruit.classList.add("garden-fruit-returning");
                    }
                }
                if(event.status!=="upcoming")fruit.append(element("span","garden-fruit-status",fallen?"!":"•"));
                const fruitDetail=`${event.type} · ${event.date_label}\n${statusLabel(event)}${fallen?" · Fallen fruit":""}`;
                fruit.setAttribute("aria-label",`${tree.subject}: ${event.title}. ${fruitDetail}`);
                interactive(fruit,{kicker:`${tree.subject} · ${event.type}`,title:event.title,detail:fruitDetail,action:"Open event"});
                attachFruit(fruit,plant,canopy,fallen);
            };
            geometry.attached.forEach((event,index)=>drawFruit(event,index,false));
            geometry.fallen.forEach((event,index)=>drawFruit(event,index,true));
            scene.append(plant);
        });
        fallenSeen.forEach(id=>{if(!currentOverdue.has(id))fallenSeen.delete(id);});
        saveStorage(sessionStorage,snapshotKey+".fallen",JSON.stringify(Array.from(fallenSeen)));
        if(!data.trees.length) {
            const empty=element("div","garden-empty");
            empty.style.top=`${plan.emptyTop}px`;
            empty.append(element("strong","","Plant your first subject"),element("p","","Your study material and important dates will grow here."));
            const start=element("a","","Add your subjects");
            start.href="/dashboard/goals/";empty.append(start);scene.append(empty);
        }
        if(completed)status.textContent=`${completed} subject review${completed===1?"":"s"} completed. Your ivy is up to date.`;
        previous=data;
        saveStorage(sessionStorage,snapshotKey,JSON.stringify(data));
    }

    async function refresh(force=false) {
        if(document.hidden || activeView!=="garden" || refreshInFlight || (!force && Date.now()-lastRefresh<15000))return;
        refreshInFlight=true;
        const url=new URL(location.href);url.search="?garden_state=1";
        try{
            const response=await fetch(url,{credentials:"same-origin",cache:"no-store",headers:{Accept:"application/json"}});
            if(!response.ok || !response.headers.get("content-type")?.includes("application/json"))throw new Error("refresh unavailable");
            const payload=await response.json();
            if(payload.garden.student!==data.student) return;
            lastRefresh=Date.now();
            if(JSON.stringify(payload.garden)!==JSON.stringify(data)){
                previous=data;data=payload.garden;
                status.textContent="";
                // This fragment is rendered by our authenticated Django view, not by uploaded content.
                standard.innerHTML=payload.standard_html;
                render();
                if(!status.textContent)status.textContent="Garden updated.";
            }
        }catch(_){ status.textContent="Couldn't refresh. Your last loaded garden is still here."; }
        finally{refreshInFlight=false;}
    }
    const observer=new ResizeObserver(()=>{
        if(activeView!=="garden" || Math.abs(scene.clientWidth-renderedWidth)<2)return;
        cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(render);
    });observer.observe(scene);
    window.addEventListener("pageshow",event=>{if(event.persisted)refresh(true);});
    window.addEventListener("focus",()=>{updateMotion();refresh();});
    document.addEventListener("visibilitychange",()=>{if(!document.hidden)refresh();});
    function updateMotion() {
        // A queued observer entry can describe the previously hidden tab. Check
        // the current scene, not entries[0], so switching views never strands it.
        const rect=scene.getBoundingClientRect();
        const visible=activeView==="garden"&&!document.hidden&&rect.width>0&&rect.height>0&&
            rect.bottom>0&&rect.top<innerHeight&&rect.right>0&&rect.left<innerWidth;
        garden.classList.toggle("garden-motion-paused",!visible);
    }
    if ("IntersectionObserver" in window) {
        const visibilityObserver=new IntersectionObserver(updateMotion);
        visibilityObserver.observe(scene);
    }
    document.addEventListener("visibilitychange",updateMotion);
    setInterval(()=>refresh(),60000);
    const requested=new URL(location.href).searchParams.get("view");
    setView(requested==='garden'?'garden':requested==='standard'?'standard':readStorage(localStorage,storageKey)||'standard');
})();
