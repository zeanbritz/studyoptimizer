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
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const svgNS = "http://www.w3.org/2000/svg";
    let selected = null, pointer = "", renderedWidth = 0, refreshInFlight = false;
    let restoringFocus = false;
    let previous = readStorage(sessionStorage, snapshotKey, true);
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
        if (activeView === "garden") { render(); refresh(); }
    }
    tabs.forEach(tab => {
        tab.addEventListener("click", () => setView(tab.dataset.planView));
        tab.addEventListener("keydown", event => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            setView(event.key === "Home" ? "standard" : event.key === "End" ? "garden" : activeView === "standard" ? "garden" : "standard", true);
        });
    });

    function closeDetails(returnFocus = false) {
        if (selected) {
            selected.classList.remove("is-selected");
            selected.removeAttribute("aria-describedby");
            if (returnFocus && selected.isConnected) {
                restoringFocus = true;
                selected.focus({ preventScroll: true });
                restoringFocus = false;
            }
        }
        selected = null;
        popover.hidden = true;
    }
    function showDetails(target, info) {
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
        const rect = target.getBoundingClientRect();
        const popup = popover.getBoundingClientRect();
        const left = Math.max(12, Math.min(innerWidth - popup.width - 12, rect.left + rect.width / 2 - popup.width / 2));
        let top = rect.top - popup.height - 12;
        if (top < 72) top = Math.min(innerHeight - popup.height - 12, rect.bottom + 12);
        position(popover, left, Math.max(12, top));
    }
    function interactive(link, info) {
        link.addEventListener("pointerenter", event => { if (event.pointerType === "mouse") showDetails(link, info); });
        link.addEventListener("focus", () => { if (!restoringFocus) showDetails(link, info); });
        link.addEventListener("pointerdown", event => { pointer = event.pointerType; });
        link.addEventListener("click", event => {
            if (event.detail && pointer !== "mouse") {
                // Touch users can inspect details and use the explicit action in the popover.
                event.preventDefault();
                showDetails(link, info);
            }
        });
    }
    popover.querySelector("button").addEventListener("click", () => closeDetails(true));
    document.addEventListener("pointerdown", event => {
        if (!popover.contains(event.target) && !event.target.closest(".garden-leaf, .garden-tree-link, .garden-fruit")) closeDetails();
    });
    document.addEventListener("keydown", event => { if (event.key === "Escape" && !popover.hidden) { event.preventDefault(); closeDetails(true); } });
    document.addEventListener("focusin", event => {
        if (!popover.hidden && !popover.contains(event.target) && event.target !== selected) closeDetails();
    });
    window.addEventListener("scroll", () => closeDetails(), { passive: true });

    const leafPaths = [
        "M10 43C8 15 31 2 57 12C82-4 111 9 108 29C123 52 97 73 68 67C43 84 14 70 10 43Z",
        "M7 40C14 13 36 7 56 14C82 2 110 10 112 32C119 59 92 76 68 67C41 78 12 66 7 40Z",
        "M8 47L19 21L39 20L56 4L73 18L103 15L115 39L98 61L73 66L54 76L35 63L15 67Z",
        "M7 39C20 22 32 9 58 13C88 0 104 18 114 39C103 61 91 72 68 66C40 78 16 61 7 39Z",
        "M9 40C18 11 40 5 60 15C83 4 107 12 112 41C106 62 87 75 64 66C42 78 17 62 9 40Z",
        "M9 38C9 17 31 5 57 15C82 3 110 14 111 39C112 62 89 75 66 65C41 78 14 66 9 38Z"
    ];
    const palettes = [["#4b8955", "#284f35"], ["#668f43", "#35552b"], ["#728c44", "#3d562b"], ["#537e5b", "#2a4938"], ["#488878", "#255345"], ["#7c8b55", "#45562f"]];
    function leafArtwork(categoryIndex, id) {
        const [light, dark] = palettes[categoryIndex];
        const safeId = `ivy-${id}`;
        return `<svg viewBox="0 0 120 80" aria-hidden="true"><defs><linearGradient id="${safeId}" x2=".7" y2="1"><stop stop-color="${light}"/><stop offset="1" stop-color="${dark}"/></linearGradient></defs><path d="${leafPaths[categoryIndex]}" fill="url(#${safeId})" stroke="#a4b975" stroke-width="1.2"/><path d="M10 47Q57 28 108 32M35 38L29 19M55 35L54 16M77 33L88 17M33 40L36 59M58 36L66 61M82 34L91 53" stroke="#c0d39a" stroke-width=".8" opacity=".3" fill="none"/></svg>`;
    }

    function treeArtwork(tree) {
        const id = `tree-${tree.id}`;
        const stage = tree.stage;
        const colors = ["#77a543", "#6a9b3a", "#54872f", "#406c2b", "#365e2d"];
        let canopy = "";
        if (stage === 1) {
            canopy = '<path d="M79 86C49 94 31 70 43 52C67 44 82 62 79 86" fill="#78ad46"/><path d="M80 86C78 57 103 35 120 46C124 72 105 86 80 86" fill="#4e893b"/><path d="M78 85L48 58M81 82L111 50" stroke="#c5d887" stroke-width="1.5"/>';
        } else if (stage > 1) {
            const scale = [0, 0, .62, .8, .94, 1][stage];
            canopy = `<g transform="translate(80 76) scale(${scale}) translate(-80 -76)">`;
            const lobes = [[55,52,30],[93,44,30],[115,72,31],[100,103,31],[62,109,29],[39,81,28],[76,77,36]];
            lobes.forEach(([x,y,r], index) => {
                canopy += `<circle cx="${x}" cy="${y}" r="${r}" fill="${colors[index % colors.length]}"/><path d="M${x-r*.5} ${y+r*.2}q${r*.2} ${-r*.8} ${r} ${-r*.5}" fill="none" stroke="#c0d280" stroke-width="2" opacity=".23"/>`;
            });
            // Crown leaves are decorative; only the six ivy plants encode review subjects.
            for (let i = 0; i < 30; i++) {
                const angle = i * 2.39996;
                const radius = 12 + Math.sqrt(i / 30) * 48;
                const x = 80 + Math.cos(angle) * radius, y = 77 + Math.sin(angle) * radius;
                canopy += `<ellipse cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" rx="8" ry="3.8" transform="rotate(${i*37} ${x} ${y})" fill="${i%3 ? '#9dbb5a' : '#234f2f'}" opacity=".5"/>`;
            }
            if (stage === 5) [[50,65],[99,51],[109,95],[70,110]].forEach(([x,y]) => {
                canopy += `<path d="M${x-3} ${y}l3-4 3 4-3 4Z" fill="#f7e4aa"/>`;
            });
            canopy += "</g>";
        }
        return `<svg class="garden-tree-art" viewBox="0 0 160 160" aria-hidden="true"><defs><radialGradient id="${id}"><stop stop-color="#3c2c1d" stop-opacity=".5"/><stop offset="1" stop-color="#3c2c1d" stop-opacity="0"/></radialGradient></defs><ellipse cx="80" cy="86" rx="71" ry="62" fill="url(#${id})"/><ellipse cx="80" cy="85" rx="${stage ? 21 : 34}" ry="${stage ? 14 : 23}" fill="#48301f" stroke="#a27a4f" stroke-width="2"/>${stage === 0 ? '<ellipse cx="79" cy="82" rx="7" ry="4" transform="rotate(-30 79 82)" fill="#deb986"/><path d="M50 105Q80 114 109 103M59 66Q79 58 100 65" stroke="#c69969" opacity=".6" fill="none"/>' : '<path d="M80 95L77 69M80 81L62 63M79 82L99 66" stroke="#937349" stroke-width="5" stroke-linecap="round" fill="none"/>'}<g class="tree-crown">${canopy}</g></svg>`;
    }
    function fruitArtwork(event) {
        const exam = event.kind === "exam";
        return exam
            ? '<svg viewBox="0 0 40 44" aria-hidden="true"><path d="M20 12Q19 4 24 2" stroke="#674f2d" stroke-width="3" fill="none"/><path d="M21 9Q28 0 33 7Q31 13 21 9" fill="#4c792f"/><path d="M20 13C5 3 0 23 7 34C12 43 17 40 20 39C25 43 33 39 36 28C40 14 30 6 20 13Z" fill="#edb84e" stroke="#ba8731" stroke-width="1.2"/><path d="M10 18Q6 23 11 29" stroke="#ffe3a0" stroke-width="3" stroke-linecap="round" fill="none"/></svg>'
            : '<svg viewBox="0 0 40 44" aria-hidden="true"><path d="M20 13Q17 5 23 2" stroke="#674f2d" stroke-width="3" fill="none"/><path d="M20 11Q27 2 32 8L25 14" fill="#587c3d"/><circle cx="20" cy="27" r="15" fill="#7b9cc8" stroke="#456785" stroke-width="1.2"/><path d="M11 22Q10 17 17 17" stroke="#d3e4f3" stroke-width="3" stroke-linecap="round" fill="none"/><path d="M16 14l4 5 4-5" stroke="#546b71" fill="none"/></svg>';
    }

    function treeHeight(tree) { return 219 + Math.max(0, Math.ceil((tree.events.length - 6) / 3)) * 49; }
    function layout(state, width) {
        const mobile = width < 630;
        const narrow = width < 275;
        const leafSpacing = narrow ? 208 : 91;
        const side = mobile ? width / 2 : Math.min(225, Math.max(170, width * .255));
        const pairs = [[0,5],[1,4],[2,3]];
        let heights = pairs.map(pair => Math.max(185, ...pair.map(i => (narrow ? 210 : 94) + Math.max(1, state.categories[i].leaves.length) * leafSpacing)));
        const trees = [], bandTops = [];
        let height = 0;
        if (mobile) {
            const split = Math.ceil(state.trees.length / 2);
            for (let band = 0; band < 3; band++) {
                bandTops.push(height); height += heights[band];
                const subset = band === 0 ? state.trees.slice(0,split) : band === 1 ? state.trees.slice(split) : [];
                subset.forEach((tree, i) => {
                    const h = treeHeight(tree);
                    trees.push({ tree, x: width/2 - 90 + (i%2 ? 13 : -13), y: height + 9, h });
                    height += h + 30;
                });
                if (band === 0 && !state.trees.length) height += 230;
            }
        } else {
            const centerWidth = width - side*2;
            const columns = Math.max(1, Math.floor(centerWidth / 190));
            let forestHeight = 45;
            for (let i=0; i<state.trees.length; i+=columns) {
                const row = state.trees.slice(i,i+columns);
                const rowHeight = Math.max(...row.map(treeHeight));
                row.forEach((tree, j) => trees.push({tree, x: side + centerWidth/2 + (j-(row.length-1)/2)*185 - 90 + (i%2?8:-8), y:forestHeight+(j%2?21:0),h:treeHeight(tree)}));
                forestHeight += rowHeight + 42;
            }
            height = Math.max(870, forestHeight+35, heights.reduce((a,b)=>a+b,0));
            const extra = (height - heights.reduce((a,b)=>a+b,0))/3;
            heights = heights.map(h=>h+extra);
            bandTops.push(0,heights[0],heights[0]+heights[1]);
        }
        const vines = state.categories.map((category,i) => {
            const band = i<3 ? i : 5-i, right=i>=3, bottom=band===2;
            const top=bandTops[band], h=heights[band];
            const offset = narrow && right ? 58 : 0;
            const origin={x:right?width-13:13,y:bottom?top+h-20-offset:top+27+offset};
            const label={x:right?width-(mobile?133:151):8,y:bottom?top+h-65-offset:top+12+offset};
            const leaves=category.leaves.map((leaf,j)=>{
                const inward=mobile?67:Math.min(side-60,82+((j%3)*27));
                const depth = (narrow ? 185 : 111) + j*leafSpacing + (narrow && right ? 104 : 0);
                return {leaf,x:right?width-inward:inward,y:bottom?top+h-depth:top+depth,angle:(right?-1:1)*(j%2?9:-7)};
            });
            return {category,i,origin,label,leaves};
        });
        return {height,trees,vines,emptyTop:mobile?heights[0]+20:230};
    }

    function drawLeaf(point, category, index, completed=false) {
        const link=element("a", `garden-leaf${completed?' garden-completed-leaf':''}`);
        link.href=point.leaf.url;
        link.dataset.leafId=point.leaf.id;
        link.style.setProperty("--leaf-angle", `${point.angle}deg`);
        link.style.setProperty("--breeze-delay", `${-(index+1)*.7}s`);
        position(link,point.x-58,point.y-38);
        link.innerHTML=leafArtwork(index,point.leaf.id+(completed?'-done':''));
        link.append(element("span","",point.leaf.subject));
        const itemWord=point.leaf.count===1?'item':'items';
        link.setAttribute("aria-label",`${point.leaf.subject}, ${category.label}, ${point.leaf.count} ${itemWord} to review`);
        if (!completed) interactive(link,{kicker:category.label,title:point.leaf.subject,detail:`${point.leaf.count} ${itemWord} to review today.`,action:category.id==='notes'?'Study notes':'Start review'});
        else { link.tabIndex=-1; link.setAttribute("aria-hidden","true"); setTimeout(()=>link.remove(),900); }
        return link;
    }

    function render() {
        const width=scene.clientWidth;
        if (!width || activeView!=="garden") return;
        renderedWidth=width;
        closeDetails();
        const plan=layout(data,width);
        const old=previous && previous.date===data.date ? layout(previous,width) : null;
        scene.replaceChildren();
        scene.style.minHeight = "0";
        scene.style.height=`${plan.height}px`;
        const stems=svg("svg",{class:"garden-stems",viewBox:`0 0 ${width} ${plan.height}`,"aria-hidden":"true"});
        scene.append(stems);
        let completed=0;
        plan.vines.forEach(vine=>{
            const group=element("section","garden-vine");
            group.setAttribute("aria-label",`${vine.category.label}, ${vine.leaves.length} subject${vine.leaves.length===1?'':'s'} to review`);
            const label=element("div","garden-vine-label");
            position(label,vine.label.x,vine.label.y);
            label.append(element("strong","",vine.category.label),element("small","",vine.leaves.length?`${vine.leaves.length} subject${vine.leaves.length===1?'':'s'} to review`:"All caught up"));
            group.append(label);
            const direction=vine.i>=3?-1:1;
            const nodes=vine.leaves.length?vine.leaves:[{x:vine.origin.x+direction*45,y:vine.origin.y+(vine.i===2||vine.i===3?-64:65)}];
            nodes.forEach((point,j)=>{
                const ox=vine.origin.x,oy=vine.origin.y;
                const curve=`M${ox} ${oy}C${ox+direction*(28+j*3)} ${oy+(point.y-oy)*.6},${point.x-direction*42} ${point.y+30},${point.x} ${point.y}`;
                stems.append(svg("path",{d:curve,class:"garden-stem-shadow"}),svg("path",{d:curve,class:j===0?"garden-stem":"garden-twig"}));
                if(point.leaf)group.append(drawLeaf(point,vine.category,vine.i));
            });
            if(old){
                const prior=old.vines.find(v=>v.category.id===vine.category.id);
                prior?.leaves.forEach(point=>{
                    if(!vine.category.leaves.some(l=>l.id===point.leaf.id)){
                        completed++;
                        if(!reducedMotion.matches)group.append(drawLeaf(point,vine.category,vine.i,true));
                    }
                });
            }
            scene.append(group);
        });
        plan.trees.forEach(({tree,x,y,h})=>{
            const plant=element("section","garden-tree");
            plant.setAttribute("aria-label",`${tree.subject} study tree`);
            position(plant,x,y);plant.style.height=`${h}px`;
            const link=element("a","garden-tree-link"); link.href=tree.url;
            link.innerHTML=treeArtwork(tree);
            const label=element("span","garden-tree-label");
            label.append(element("strong","",tree.subject),element("small","",tree.progress===null?"Add textbook pages":`${tree.progress}% summarized`));
            link.append(label);
            const detail=tree.progress===null?"No textbook page total yet. Add a textbook to watch this tree grow.":`${tree.summarized_pages} of ${tree.total_pages} pages summarized (${tree.progress}%).${tree.today_pages?`\nToday's study target: ${tree.today_pages} page${tree.today_pages===1?'':'s'}.`:''}`;
            link.setAttribute("aria-label",`${tree.subject}. ${detail}`);
            interactive(link,{kicker:"Study · Summarizing progress",title:tree.subject,detail,action:"Open Study"});
            plant.append(link);
            const prior=previous?.trees.find(t=>t.id===tree.id);
            if(prior && prior.progress!==tree.progress && !reducedMotion.matches)link.querySelector("svg").classList.add("garden-growth");
            const supports=svg("svg",{class:"garden-fruit-stem",viewBox:`0 0 180 ${h}`,"aria-hidden":"true"});
            plant.append(supports);
            tree.events.forEach((event,i)=>{
                const angle=(-150+i*60)*Math.PI/180;
                const fx=i<6?90+Math.cos(angle)*62:90+((i-6)%3-1)*49;
                const fy=i<6?76+Math.sin(angle)*53:169+Math.floor((i-6)/3)*49;
                supports.append(svg("path",{d:`M90 81Q${fx} ${fy-15} ${fx} ${fy}`}));
                const fruit=element("a","garden-fruit"); fruit.href=event.url; fruit.dataset.status=event.status;
                position(fruit,fx-22,fy-22);fruit.innerHTML=fruitArtwork(event);
                if(event.status!=="upcoming")fruit.append(element("span","garden-fruit-status",event.completed?'✓':event.status==='overdue'?'!':'•'));
                const detail=`${event.type} · ${event.date_label}\n${statusLabel(event)}`;
                fruit.setAttribute("aria-label",`${tree.subject}: ${event.title}. ${detail}`);
                interactive(fruit,{kicker:`${tree.subject} · ${event.type}`,title:event.title,detail,action:"Open event"});
                plant.append(fruit);
            });
            scene.append(plant);
        });
        if(!data.trees.length){
            const empty=element("div","garden-empty");empty.style.top=`${plan.emptyTop}px`;
            empty.append(element("strong","","Plant your first subject"),element("p","","Your study material and important dates will grow here."));
            const start=element("a","","Add your subjects");start.href="/dashboard/goals/";empty.append(start);scene.append(empty);
        }
        if(completed)status.textContent=`${completed} subject review${completed===1?'':'s'} completed. Your ivy is up to date.`;
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
    window.addEventListener("focus",()=>refresh());
    document.addEventListener("visibilitychange",()=>{if(!document.hidden)refresh();});
    setInterval(()=>refresh(),60000);
    const requested=new URL(location.href).searchParams.get("view");
    setView(requested==='garden'?'garden':readStorage(localStorage,storageKey)||'standard');
})();
