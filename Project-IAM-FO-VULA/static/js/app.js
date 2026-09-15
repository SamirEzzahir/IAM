// Resolve application URLs relative to the page so standalone `/` and the
// combined `/VULA/` route behave identically.
function appUrl(path){return new URL(String(path).replace(/^\/+/,""),document.baseURI).toString()}

const DB_NAME="VULA_Control_Center_DB",DB_VERSION=2,STORE_NAME="configuration";
let dataVULA_Text=null,dataPCO_Text=null,dataOccupation_Text=null,dataClients_Text=null,occupationIndex=new Map(),clientRows=[],clientIndex={adresse:new Map(),nom:new Map(),login:new Map(),serie:new Map()},polygonesVULA=[],placemarkCache=null,clientResultRows=[],clientResultPage=0,clientPageSize=100,clientStatusCache=new Map(),
metadata={VULA:{name:"",size:0,updated:null},PCO:{name:"",size:0,updated:null},OCCUPATION:{name:"",size:0,updated:null},CLIENTS:{name:"",size:0,updated:null}};
function showLoading(t){document.getElementById("loadingText").textContent=t||"Chargement...";document.getElementById("loading").style.display="flex"}function hideLoading(){document.getElementById("loading").style.display="none"}function toast(m){const t=document.getElementById("toast");t.textContent=m;t.style.display="block";clearTimeout(window.__toast);window.__toast=setTimeout(()=>t.style.display="none",4000)}
function setStatus(type,ok,text){const d=document.getElementById(type+"Dot"),l=document.getElementById(type+"Status");d.className="dot "+(ok?"ok":"bad");l.textContent=text}function setConfigStatus(type,ok,text){const e=document.getElementById(type.toLowerCase()+"ConfigStatus");if(!e)return;e.className="config-status "+(ok?"ok":"bad");e.textContent=text}
function switchTab(tab,btn){document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));document.querySelectorAll(".nav button").forEach(x=>x.classList.remove("active"));document.getElementById("tab-"+tab).classList.add("active");if(btn)btn.classList.add("active")}
function formatBytes(b){if(!Number.isFinite(b)||b<=0)return"0 octet";const u=["octets","Ko","Mo","Go"],i=Math.floor(Math.log(b)/Math.log(1024));return`${(b/Math.pow(1024,i)).toFixed(i?1:0)} ${u[i]}`}
function updateConfigUI(){
    metadata.CLIENTS=metadata.CLIENTS||{name:"",size:0,updated:null}; const v=metadata.VULA,p=metadata.PCO,o=metadata.OCCUPATION,c=metadata.CLIENTS;
    document.getElementById("vulaFileName").textContent=v.name?`${v.name} · ${formatBytes(v.size)}`:"Aucun fichier configuré";
    document.getElementById("pcoFileName").textContent=p.name?`${p.name} · ${formatBytes(p.size)}`:"Aucun fichier configuré";
    document.getElementById("occupationFileName").textContent=o.name?`${o.name} · ${formatBytes(o.size)}`:"Aucun fichier configuré";
    const cf=document.getElementById("clientsFileName"); if(cf) cf.textContent=c&&c.name?`${c.name} · ${formatBytes(c.size)}`:"Aucun fichier configuré";
    if(dataVULA_Text&&polygonesVULA.length){setConfigStatus("VULA",true,`${polygonesVULA.length} zones`);setStatus("vula",true,`${polygonesVULA.length} zones VULA`)}
    else{setConfigStatus("VULA",false,"Non configuré");setStatus("vula",false,"VULA non chargé")}
    if(dataPCO_Text){const c=getPlacemarkData().length;setConfigStatus("PCO",true,`${c} PCO`);setStatus("pco",true,`${c} PCO chargés`)}
    else{setConfigStatus("PCO",false,"Non configuré");setStatus("pco",false,"PCO non chargé")}
    if(dataOccupation_Text&&occupationIndex.size){setConfigStatus("OCCUPATION",true,`${occupationIndex.size} PCO`)}
    else{setConfigStatus("OCCUPATION",false,"Non configuré")}
    if(dataClients_Text&&clientRows.length){setConfigStatus("CLIENTS",true,`${clientRows.length} clients`)}
    else{setConfigStatus("CLIENTS",false,"Non configuré")}
    document.getElementById("firstUseNotice").style.display=(!dataVULA_Text||!dataPCO_Text||!polygonesVULA.length)?"block":"none"
}
function openDB(){return new Promise((res,rej)=>{if(!window.indexedDB)return rej(Error("IndexedDB non disponible"));const r=indexedDB.open(DB_NAME,DB_VERSION);r.onupgradeneeded=e=>{const db=e.target.result;if(!db.objectStoreNames.contains(STORE_NAME))db.createObjectStore(STORE_NAME)};r.onsuccess=()=>res(r.result);r.onerror=()=>rej(r.error||Error("Ouverture IndexedDB impossible"))})}
async function dbSet(k,v){const db=await openDB();return new Promise((res,rej)=>{const tx=db.transaction(STORE_NAME,"readwrite");tx.objectStore(STORE_NAME).put(v,k);tx.oncomplete=()=>{db.close();res(true)};tx.onerror=()=>{db.close();rej(tx.error)}})}async function dbGet(k){const db=await openDB();return new Promise((res,rej)=>{const tx=db.transaction(STORE_NAME,"readonly"),r=tx.objectStore(STORE_NAME).get(k);r.onsuccess=()=>res(r.result);r.onerror=()=>rej(r.error);tx.oncomplete=()=>db.close()})}async function dbClear(){const db=await openDB();return new Promise((res,rej)=>{const tx=db.transaction(STORE_NAME,"readwrite");tx.objectStore(STORE_NAME).clear();tx.oncomplete=()=>{db.close();res(true)};tx.onerror=()=>{db.close();rej(tx.error)}})}
function localSet(k,v){localStorage.setItem("VULA_"+k,JSON.stringify(v))}function localGet(k){const x=localStorage.getItem("VULA_"+k);return x?JSON.parse(x):null}function localClear(){["VULA_TEXT","PCO_TEXT","OCCUPATION_TEXT","CLIENTS_TEXT","METADATA"].forEach(k=>localStorage.removeItem("VULA_"+k))}
async function saveLocalData(){try{await dbSet("VULA_TEXT",dataVULA_Text);await dbSet("PCO_TEXT",dataPCO_Text);await dbSet("OCCUPATION_TEXT",dataOccupation_Text);await dbSet("CLIENTS_TEXT",dataClients_Text);await dbSet("METADATA",metadata);return}catch(e){try{localSet("VULA_TEXT",dataVULA_Text);localSet("PCO_TEXT",dataPCO_Text);localSet("OCCUPATION_TEXT",dataOccupation_Text);localSet("CLIENTS_TEXT",dataClients_Text);localSet("METADATA",metadata)}catch(e2){throw Error("Le navigateur ne permet pas de conserver ces données localement.")}}}
async function loadLocalData(){try{const v=await dbGet("VULA_TEXT"),p=await dbGet("PCO_TEXT"),o=await dbGet("OCCUPATION_TEXT"),c=await dbGet("CLIENTS_TEXT"),m=await dbGet("METADATA");if(v||p||o||c){dataVULA_Text=v||null;dataPCO_Text=p||null;dataOccupation_Text=o||null;dataClients_Text=c||null;metadata=m||metadata;return true}}catch(e){}try{dataVULA_Text=localGet("VULA_TEXT");dataPCO_Text=localGet("PCO_TEXT");dataOccupation_Text=localGet("OCCUPATION_TEXT");dataClients_Text=localGet("CLIENTS_TEXT");metadata=localGet("METADATA")||metadata;return!!(dataVULA_Text||dataPCO_Text||dataOccupation_Text||dataClients_Text)}catch(e){return false}}
function isKMLorKMZ(f){const n=(f.name||"").toLowerCase();return n.endsWith(".kml")||n.endsWith(".kmz")}
async function fichierVersKML(file){if(!file||!isKMLorKMZ(file))throw Error("Veuillez sélectionner un fichier KML ou KMZ.");const n=file.name.toLowerCase();if(n.endsWith(".kml"))return await file.text();if(!window.JSZip)throw Error("Le module de lecture KMZ (JSZip) n'est pas disponible.");const zip=await JSZip.loadAsync(await file.arrayBuffer()),kn=Object.keys(zip.files).find(x=>x.toLowerCase().endsWith(".kml")&&!zip.files[x].dir);if(!kn)throw Error("Aucun fichier KML trouvé à l'intérieur du KMZ.");return await zip.files[kn].async("string")}

function normaliserClePCO(s){return nettoyerTexte(s)}
function lireExcelOccupation(buffer,name){
    if(!window.XLSX)throw Error("Le module de lecture Excel n'est pas disponible.");
    const wb=XLSX.read(buffer,{type:"array",cellDates:false});
    if(!wb.SheetNames.length)throw Error("Aucune feuille trouvée dans le fichier Excel.");
    const ws=wb.Sheets[wb.SheetNames[0]];
    const rows=XLSX.utils.sheet_to_json(ws,{defval:"",raw:false});
    if(!rows.length)throw Error("La feuille Excel est vide.");
    const headers=Object.keys(rows[0]);
    const pcoHeader=headers.find(h=>String(h).trim().toUpperCase()==="PCO");
    const occHeader=headers.find(h=>String(h).trim().toUpperCase()==="NBRE_OCCUPE");
    const portHeader=headers.find(h=>String(h).trim().toUpperCase()==="NBRE_PORT");
    if(!pcoHeader)throw Error('Colonne "PCO" introuvable dans le fichier Excel.');
    if(!occHeader)throw Error('Colonne "NBRE_OCCUPE" introuvable dans le fichier Excel.');
    if(!portHeader)throw Error('Colonne "NBRE_PORT" introuvable dans le fichier Excel.');
    const map=new Map();
    let valid=0;
    rows.forEach(row=>{
        const pco=String(row[pcoHeader]??"").trim();
        if(!pco)return;
        const key=normaliserClePCO(pco);
        if(!key)return;
        const port=Number(String(row[portHeader]??"").trim().replace(",",".")); 
        const occ=Number(String(row[occHeader]??"").trim().replace(",","."));
        map.set(key,{
            pco,
            nbrePort:Number.isFinite(port)?port:null,
            nbreOccupe:Number.isFinite(occ)?occ:null
        });
        valid++;
    });
    if(!valid)throw Error("Aucune ligne PCO exploitable dans le fichier Excel.");
    return map;
}
function getOccupationPCO(key){
    return occupationIndex.get(normaliserClePCO(key))||null;
}
function occupationInfo(x){
    const o=getOccupationPCO(x.key);
    if(!o)return {found:false,nbrePort:null,nbreOccupe:null,libres:null,state:"NON TROUVÉ"};
    const port=o.nbrePort,occ=o.nbreOccupe;
    const libres=(Number.isFinite(port)&&Number.isFinite(occ))?port-occ:null;
    if(!Number.isFinite(port)||!Number.isFinite(occ))return {found:true,nbrePort:port,nbreOccupe:occ,libres:null,state:"DONNÉES INCOMPLÈTES"};
    if(port===occ)return {found:true,nbrePort:port,nbreOccupe:occ,libres:0,state:"SATURÉ"};
    if(port>occ)return {found:true,nbrePort:port,nbreOccupe:occ,libres:libres,state:"PORTS LIBRES"};
    return {found:true,nbrePort:port,nbreOccupe:occ,libres:libres,state:"VÉRIFIER DONNÉES"};
}
function getRowClassification(x){
    const occ=occupationInfo(x);
    if(!x.in)return {className:"row-out",statusClass:"out",label:"OUT VULA",occ};
    if(!occ.found)return {className:"row-na",statusClass:"na",label:"NON TROUVÉ",occ};
    if(occ.state==="SATURÉ")return {className:"row-saturated",statusClass:"saturated",label:"SATURÉ",occ};
    if(occ.state==="PORTS LIBRES")return {className:"row-free",statusClass:"free",label:"PORTS LIBRES",occ};
    return {className:"row-na",statusClass:"na",label:occ.state,occ};
}
async function importerFichierOccupation(input){
    const f=input.files&&input.files[0];if(!f)return;
    try{
        showLoading("Import du fichier Excel d'occupation...");
        const buffer=await f.arrayBuffer();
        const map=lireExcelOccupation(buffer,f.name);
        occupationIndex=map;
        dataOccupation_Text=await blobToDataURL(new Blob([buffer]));
        metadata.OCCUPATION={name:f.name,size:f.size,updated:new Date().toISOString()};
        await saveLocalData();
        updateConfigUI();
        toast(`${f.name} enregistré · ${occupationIndex.size} PCO indexés.`);
        input.value="";
    }catch(e){console.error(e);toast(e.message||"Erreur lors de l'import Excel.");input.value=""}
    finally{hideLoading()}
}
function arrayBufferFromDataURL(dataUrl){
    const b64=dataUrl.split(",")[1]||"";
    const bin=atob(b64),len=bin.length,u8=new Uint8Array(len);
    for(let i=0;i<len;i++)u8[i]=bin.charCodeAt(i);
    return u8.buffer;
}
async function blobToDataURL(blob){
    return await new Promise((resolve,reject)=>{
        const r=new FileReader();
        r.onload=()=>resolve(r.result);
        r.onerror=()=>reject(r.error||Error("Lecture du fichier impossible."));
        r.readAsDataURL(blob);
    });
}
function chargerIndexOccupationDepuisDonnees(){
    if(!dataOccupation_Text)return;
    try{
        const buffer=arrayBufferFromDataURL(dataOccupation_Text);
        occupationIndex=lireExcelOccupation(buffer,metadata.OCCUPATION.name||"occupation.xlsx");
    }catch(e){console.error("Occupation Excel:",e);occupationIndex=new Map();}
}
async function importerFichierSelectionne(input,type){const f=input.files&&input.files[0];if(!f)return;try{showLoading(`Import du fichier ${type}...`);const text=await fichierVersKML(f);if(!text||!text.trim())throw Error("Le fichier est vide.");if(type==="VULA"){const polys=extraireTousLesPolygones(text);if(!polys.length)throw Error("Aucun polygone valide n'a été trouvé dans ce fichier.");dataVULA_Text=text;polygonesVULA=polys;clientStatusCache=new Map();metadata.VULA={name:f.name,size:f.size,updated:new Date().toISOString()}}else{const old=dataPCO_Text;dataPCO_Text=text;placemarkCache=null;clientStatusCache=new Map();const c=getPlacemarkData().length;if(!c){dataPCO_Text=old;throw Error("Aucun PCO avec une coordonnée Point valide n'a été trouvé.")}metadata.PCO={name:f.name,size:f.size,updated:new Date().toISOString()}}await saveLocalData();updateConfigUI();toast(type==="VULA"?`${metadata.VULA.name} enregistré · ${polygonesVULA.length} zones chargées.`:`${metadata.PCO.name} enregistré · ${getPlacemarkData().length} PCO chargés.`);input.value=""}catch(e){console.error(e);toast(e.message||"Erreur lors de l'import.");input.value=""}finally{hideLoading()}}
async function reinitialiserConfiguration(){if(!confirm("Voulez-vous supprimer la configuration locale VULA/PCO de ce navigateur ?\n\nLes fichiers d'origine ne seront pas supprimés."))return;try{showLoading("Réinitialisation...");try{await dbClear()}catch(e){}try{localClear()}catch(e){}dataVULA_Text=null;dataPCO_Text=null;dataOccupation_Text=null;placemarkCache=null;clientStatusCache=new Map();dataClients_Text=null;occupationIndex=new Map();clientRows=[];clientIndex={adresse:new Map(),nom:new Map(),login:new Map(),serie:new Map()};polygonesVULA=[];metadata={VULA:{name:"",size:0,updated:null},PCO:{name:"",size:0,updated:null},OCCUPATION:{name:"",size:0,updated:null},CLIENTS:{name:"",size:0,updated:null}};document.getElementById("zoneStats").innerHTML="";document.getElementById("zoneResults").innerHTML="";document.getElementById("listStats").innerHTML="";document.getElementById("listResults").innerHTML="";document.getElementById("searchResult").style.display="none";updateConfigUI();toast("Configuration locale réinitialisée.")}catch(e){toast("Impossible de réinitialiser la configuration.")}finally{hideLoading()}}
function nettoyerTexte(s){return s?s.toUpperCase().replace(/[\r\n\t\s_\-]/g,""):""}
function parsePointGPS(s){if(!s)return null;const p=s.trim().replace(/\s+/g,"").split(",");if(p.length<2)return null;const lng=Number(p[0]),lat=Number(p[1]);if(!Number.isFinite(lat)||!Number.isFinite(lng))return null;return{lat,lng,raw:s.trim()}}
function parseUserGPS(str){
    if(!str)return null;

    let s=str
        .trim()
        .replace(/[\r\n\t\u00A0]/g," ")
        .replace(/[\/;:]/g," ")
        .replace(/\s+/g," ")
        .trim();

    // Format avec virgule décimale :
    // 34,005032 -5,011616
    let match=s.match(/^([+-]?\d+(?:,\d+)?)\s+([+-]?\d+(?:,\d+)?)$/);

    if(match){
        let lat=Number(match[1].replace(",", "."));
        let lng=Number(match[2].replace(",", "."));

        if(!Number.isFinite(lat)||!Number.isFinite(lng))return null;
        if(lat<20||lat>37)return null;

        if(lng>0)lng=-lng;

        return {
            lat,
            lng,
            raw:`${lat.toFixed(6)}, ${lng.toFixed(6)}`
        };
    }

    // Format avec point décimal :
    // 34.005032 -5.011616
    match=s.match(/^([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)$/);

    if(match){
        let lat=Number(match[1]);
        let lng=Number(match[2]);

        if(!Number.isFinite(lat)||!Number.isFinite(lng))return null;
        if(lat<20||lat>37)return null;

        if(lng>0)lng=-lng;

        return {
            lat,
            lng,
            raw:`${lat.toFixed(6)}, ${lng.toFixed(6)}`
        };
    }

    return null;
}
function extrairePointPCO(pm){const p=pm.getElementsByTagName("Point")[0];if(!p)return null;const n=p.getElementsByTagName("coordinates")[0];if(!n)return null;return parsePointGPS(n.textContent.trim().split(/\s+/)[0])}
function extraireTousLesPolygones(kml){const d=new DOMParser().parseFromString(kml,"text/xml");if(d.getElementsByTagName("parsererror").length)throw Error("Le KML des polygones est invalide.");const out=[];for(const poly of d.getElementsByTagName("Polygon")){const c=poly.getElementsByTagName("coordinates")[0];if(!c)continue;const pts=c.textContent.trim().split(/\s+/).map(parsePointGPS).filter(Boolean);if(pts.length>=3)out.push(pts)}return out}
function pointDansPolygone(pt,poly){let inside=false,j=poly.length-1;for(let i=0;i<poly.length;i++){const a=poly[i],b=poly[j];if((a.lat>pt.lat)!==(b.lat>pt.lat)){const d=b.lat-a.lat;if(d!==0&&pt.lng<((b.lng-a.lng)*(pt.lat-a.lat)/d+a.lng))inside=!inside}j=i}return inside}function estPointDansPolygones(lat,lng){const pt={lat,lng};return polygonesVULA.some(p=>pointDansPolygone(pt,p))}
function getPlacemarkData(){
    if(!dataPCO_Text)return[];
    if(placemarkCache)return placemarkCache;
    const d=new DOMParser().parseFromString(dataPCO_Text,"text/xml"),u=new Map;
    Array.from(d.getElementsByTagName("Placemark")).forEach(pm=>{
        const n=pm.getElementsByTagName("name")[0];if(!n)return;
        const name=n.textContent.trim(),pt=extrairePointPCO(pm);if(!pt)return;
        const key=nettoyerTexte(name);if(!u.has(key))u.set(key,{name,pt,key});
    });
    placemarkCache=Array.from(u.values());
    return placemarkCache;
}
function getPCOMap(){
    const m=new Map();
    for(const x of getPlacemarkData()) if(!m.has(x.key))m.set(x.key,x);
    return m;
}
function renderResult(title,pt,source,pcoKey=null){
    const inside=estPointDansPolygones(pt.lat,pt.lng),r=document.getElementById("searchResult");
    const occ=pcoKey?occupationInfo({key:pcoKey,in:inside}):null;
    r.style.display="block";
    let extra="";
    if(pcoKey){
        extra=`<div class="data-box"><small>NBRE PORT</small><strong>${occ&&occ.nbrePort!==null?occ.nbrePort:"—"}</strong></div>
        <div class="data-box"><small>NBRE OCCUPÉ</small><strong>${occ&&occ.nbreOccupe!==null?occ.nbreOccupe:"—"}</strong></div>
        <div class="data-box"><small>PORTS LIBRES</small><strong>${occ&&occ.libres!==null?occ.libres:"—"}</strong></div>
        <div class="data-box"><small>ÉTAT PORTS</small><strong>${occ?escapeHtml(occ.state):"—"}</strong></div>`;
    }
    r.innerHTML=`<div class="result-head"><div><div class="result-title">${escapeHtml(title)}</div><div class="result-sub">${escapeHtml(source)}</div></div><div class="big-status ${inside?"in":"out"}">${inside?"✓ IN ZONE VULA":"✕ OUT ZONE VULA"}</div></div><div class="result-data">
    <div class="data-box"><small>Latitude</small><strong>${pt.lat.toFixed(6)}</strong></div>
    <div class="data-box"><small>Longitude</small><strong>${pt.lng.toFixed(6)}</strong></div>
    <div class="data-box"><small>Statut VULA</small><strong>${inside?"PCO éligible à l'étude":"PCO non éligible"}</strong></div>${extra}</div>`;
}
function searchPCO(){if(!dataPCO_Text||!polygonesVULA.length)return toast("Les fichiers VULA/PCO ne sont pas prêts.");const q=document.getElementById("pcoSearch").value.trim();if(!q)return toast("Saisissez un PCO.");const key=nettoyerTexte(q),items=getPlacemarkData().filter(x=>x.key.includes(key)),box=document.getElementById("matches");box.innerHTML="";if(!items.length){box.innerHTML='<div class="empty">Aucun PCO correspondant.</div>';document.getElementById("searchResult").style.display="none";return}const selected=items[0];renderResult(selected.name,selected.pt,"Coordonnée extraite du <Point> KML",selected.key);if(items.length>1){box.innerHTML=`<div class="helper">${items.length} correspondances trouvées.</div>`;items.forEach(x=>{const div=document.createElement("div");div.className="match";const inside=estPointDansPolygones(x.pt.lat,x.pt.lng);const oi=occupationInfo({key:x.key,in:inside}); const oc=inside?(oi.state==="SATURÉ"?"saturated":oi.state==="PORTS LIBRES"?"free":"na"):"out"; div.innerHTML=`<div><strong>${escapeHtml(x.name)}</strong><div class="helper">${x.pt.lat.toFixed(6)}, ${x.pt.lng.toFixed(6)} · Ports: ${oi.nbrePort??"—"} · Occupés: ${oi.nbreOccupe??"—"}</div></div><span class="occupation-status ${oc}">${inside?escapeHtml(oi.state):"OUT VULA"}</span>`;box.appendChild(div)})}}
function testGPS(){if(!polygonesVULA.length)return toast("Les zones VULA ne sont pas prêtes.");const pt=parseUserGPS(document.getElementById("gpsSearch").value);if(!pt)return toast("CGPS invalide. Exemple : 34.033575, -4.990342");document.getElementById("matches").innerHTML="";renderResult("Test CGPS",pt,"Coordonnée saisie manuellement")}
function clearSearch(){document.getElementById("pcoSearch").value="";document.getElementById("gpsSearch").value="";document.getElementById("matches").innerHTML="";document.getElementById("searchResult").style.display="none"}
function analyserZone(){if(!dataPCO_Text||!polygonesVULA.length)return toast("Les fichiers ne sont pas prêts.");const prefix=nettoyerTexte(document.getElementById("inputZone").value.trim()),items=getPlacemarkData().filter(x=>!prefix||x.key.includes(prefix)),rows=items.map(x=>({name:x.name,pt:x.pt,key:x.key,in:estPointDansPolygones(x.pt.lat,x.pt.lng)}));renderTable("zoneResults","zoneStats",rows,0)}
function analyserListePCO(){if(!dataPCO_Text||!polygonesVULA.length)return toast("Les fichiers ne sont pas prêts.");const list=document.getElementById("inputListePCO").value.split(/[\r\n,;]+/).map(x=>x.trim()).filter(Boolean),items=getPlacemarkData(),rows=[],used=new Set();let na=0;list.forEach(q=>{const key=nettoyerTexte(q),found=items.find(x=>x.key===key)||items.find(x=>x.key.includes(key));if(found){if(used.has(found.key))return;used.add(found.key);rows.push({name:found.name,pt:found.pt,key:found.key,in:estPointDansPolygones(found.pt.lat,found.pt.lng)})}else{na++;rows.push({name:q,pt:null,in:false,na:true})}});renderTable("listResults","listStats",rows,na)}
function extraireZoneReseau(nom){
    const s=String(nom || "").toUpperCase();
    let m=s.match(/\bZONE[\s_\-]*(\d+(?:[.,]\d+)?)/i);
    if(!m) m=s.match(/\bZ[\s_\-]*(\d+(?:[.,]\d+)?)/i);
    return m ? {num:Number(m[1].replace(",",".")), text:m[0]} : {num:Infinity,text:s};
}
function prioritePCO(x){
    if(x.na) return 4;
    if(!x.in) return 3;
    const o=occupationInfo(x);
    if(o.found && o.state==="PORTS LIBRES") return 1;
    if(o.found && o.state==="SATURÉ") return 2;
    return 4;
}
function comparerZoneReseau(a,b){
    const pa=prioritePCO(a), pb=prioritePCO(b);
    if(pa!==pb) return pa-pb;

    // À priorité égale, conserver le tri par zone réseau puis par PCO.
    const za=extraireZoneReseau(a.name), zb=extraireZoneReseau(b.name);
    if(za.num!==zb.num) return za.num-zb.num;
    return String(a.name).localeCompare(String(b.name),"fr",{numeric:true,sensitivity:"base"});
}

function renderTable(target,statsId,rows,na){
    rows.sort(comparerZoneReseau);
    const total=rows.filter(x=>!x.na).length;
    const inRows=rows.filter(x=>x.in&&!x.na);
    const inN=inRows.length;
    const outN=rows.filter(x=>!x.in&&!x.na).length;
    const enriched=inRows.map(x=>({x,occ:occupationInfo(x)}));
    const saturated=enriched.filter(z=>z.occ.found&&z.occ.state==="SATURÉ").length;
    const free=enriched.filter(z=>z.occ.found&&z.occ.state==="PORTS LIBRES").length;
    document.getElementById(statsId).innerHTML=`<div class="stats">
    <div class="stat"><small>TOTAL</small><strong>${total}</strong></div>
    <div class="stat"><small>IN VULA</small><strong>${inN}</strong></div>
    <div class="stat"><small>SATURÉS</small><strong>${saturated}</strong></div>
    <div class="stat"><small>PORTS LIBRES</small><strong>${free}</strong></div>
    <div class="stat"><small>OUT VULA</small><strong>${outN}</strong></div>
    <div class="stat"><small>NON TROUVÉS EXCEL</small><strong>${na+enriched.filter(z=>!z.occ.found).length}</strong></div>
    </div>`;
    let h='<div class="results"><table><thead><tr><th>PCO</th><th>CGPS</th><th>VULA</th><th>NBRE PORT</th><th>NBRE OCCUPÉ</th><th>PORTS LIBRES</th><th>ÉTAT</th></tr></thead><tbody>';
    rows.forEach(x=>{
        if(x.na){
            h+=`<tr class="row-na"><td><strong>${escapeHtml(x.name)}</strong></td><td>—</td><td><span class="occupation-status na">NON TROUVÉ</span></td><td>—</td><td>—</td><td>—</td><td><span class="occupation-status na">PCO NON TROUVÉ</span></td></tr>`;
            return;
        }
        const c=getRowClassification(x),o=c.occ;
        const vulaBadge=x.in?`<span class="badge in">IN</span>`:`<span class="occupation-status out">OUT</span>`;
        const stateText=x.in?c.label:"OUT VULA";
        h+=`<tr class="${c.className}">
        <td><strong>${escapeHtml(x.name)}</strong></td>
        <td>${x.pt.lat.toFixed(6)}, ${x.pt.lng.toFixed(6)}</td>
        <td>${vulaBadge}</td>
        <td>${o.nbrePort??"—"}</td>
        <td>${o.nbreOccupe??"—"}</td>
        <td>${o.libres!==null?o.libres:"—"}</td>
        <td><span class="occupation-status ${c.statusClass}">${escapeHtml(stateText)}</span></td>
        </tr>`;
    });
    h+='</tbody></table></div>';
    document.getElementById(target).innerHTML=h;
}

function normaliserRechercheClient(v){return String(v??"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toUpperCase().replace(/[\s\u00A0\-_./]+/g,"").trim()}
function detectHeader(headers,name){const target=normaliserRechercheClient(name);return headers.find(h=>normaliserRechercheClient(h)===target)}
function chargerClientsDepuisBuffer(buffer,name){
    if(!window.XLSX)throw Error("Le module de lecture Excel n'est pas disponible.");
    const wb=XLSX.read(buffer,{type:"array",cellDates:false});
    if(!wb.SheetNames.length)throw Error("Aucune feuille trouvée.");
    const rows=XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]],{defval:"",raw:false});
    if(!rows.length)throw Error("La feuille clients est vide.");
    const headers=Object.keys(rows[0]);
    const required=["ODF","Login","Série ONT","Nom Client","Adresse Client","NE","PCO","OLT"];
    const H={};required.forEach(x=>H[x]=detectHeader(headers,x));
    const missing=required.filter(x=>!H[x]);if(missing.length)throw Error("Colonnes manquantes : "+missing.join(", "));
    clientRows=rows.map(r=>{
        const obj={odf:String(r[H["ODF"]]??"").trim(),login:String(r[H["Login"]]??"").trim(),serie:String(r[H["Série ONT"]]??"").trim(),nom:String(r[H["Nom Client"]]??"").trim(),adresse:String(r[H["Adresse Client"]]??"").trim(),ne:String(r[H["NE"]]??"").trim(),pco:String(r[H["PCO"]]??"").trim(),olt:String(r[H["OLT"]]??"").trim()};
        obj._norm={adresse:normaliserRechercheClient(obj.adresse),nom:normaliserRechercheClient(obj.nom),login:normaliserRechercheClient(obj.login),serie:normaliserRechercheClient(obj.serie),pco:normaliserClePCO(obj.pco)};
        return obj;
    });
    clientIndex={adresse:new Map(),nom:new Map(),login:new Map(),serie:new Map()};
    for(const row of clientRows){for(const k of Object.keys(clientIndex)){const key=row._norm[k];if(!key)continue;if(!clientIndex[k].has(key))clientIndex[k].set(key,[]);clientIndex[k].get(key).push(row);}}
    clientStatusCache=new Map();
}
async function importerFichierClients(input){const f=input.files&&input.files[0];if(!f)return;try{showLoading("Import de la base clients...");const b=await f.arrayBuffer();chargerClientsDepuisBuffer(b,f.name);dataClients_Text=await blobToDataURL(new Blob([b]));metadata.CLIENTS={name:f.name,size:f.size,updated:new Date().toISOString()};await saveLocalData();updateConfigUI();toast(`${f.name} enregistré · ${clientRows.length} clients.`);input.value=""}catch(e){console.error(e);toast(e.message||"Erreur lors de l'import de la base clients.");input.value=""}finally{hideLoading()}}
function chargerIndexClientsDepuisDonnees(){if(!dataClients_Text)return;try{chargerClientsDepuisBuffer(arrayBufferFromDataURL(dataClients_Text),metadata.CLIENTS?.name||"clients.xlsx")}catch(e){console.error(e);clientRows=[];clientIndex={adresse:new Map(),nom:new Map(),login:new Map(),serie:new Map()}}}
let clientSearchMode="adresse";
function choisirRechercheClient(mode){clientSearchMode=mode;const labels={adresse:"Recherche par Adresse Client",nom:"Recherche par Nom Client",login:"Recherche par Login",serie:"Recherche par Série ONT"};document.getElementById("clientSearchLabel").textContent=labels[mode];document.querySelectorAll("#clientModeButtons button").forEach((b,i)=>{const active=Object.keys(labels)[i]===mode;b.classList.remove("primary","secondary");b.classList.add(active?"primary":"secondary");});document.getElementById("clientSearchInput").focus()}
function effacerRechercheClient(){document.getElementById("clientSearchInput").value="";clientResultRows=[];clientResultPage=0;clientPageSize=100;document.getElementById("clientStats").innerHTML="";document.getElementById("clientResults").innerHTML="";}
function rechercherClients(){
    if(!clientRows.length)return toast("La base clients Excel n'est pas chargée.");
    const q=normaliserRechercheClient(document.getElementById("clientSearchInput").value);
    if(!q)return toast("Saisissez une valeur de recherche.");
    const field=clientSearchMode;
    // Recherche sur les valeurs déjà normalisées : aucune normalisation répétée sur 30 000 lignes.
    const rows=clientRows.filter(r=>r._norm[field].includes(q));
    clientResultRows=rows.sort(comparerClientsParVula);clientResultPage=0;clientPageSize=100;
    renderClientResultsPage(q);
}
function getClientPCOStatus(pco){
    const key=normaliserClePCO(pco);
    if(!key)return {found:false};
    if(clientStatusCache.has(key))return clientStatusCache.get(key);
    const item=getPCOMap().get(key);
    if(!item){const miss={found:false};clientStatusCache.set(key,miss);return miss;}
    const inside=estPointDansPolygones(item.pt.lat,item.pt.lng),occ=occupationInfo({key:item.key,in:inside});
    const result={found:true,inside,pt:item.pt,occ};clientStatusCache.set(key,result);return result;
}
function prioriteClientParVula(row){
    const st=getClientPCOStatus(row.pco);
    if(!st.found || !st.inside) return 3;
    if(st.occ && st.occ.state==="PORTS LIBRES") return 1;
    if(st.occ && st.occ.state==="SATURÉ") return 2;
    return 3;
}
function comparerClientsParVula(a,b){
    const pa=prioriteClientParVula(a), pb=prioriteClientParVula(b);
    if(pa!==pb) return pa-pb;
    return String(a.pco||"").localeCompare(String(b.pco||""),"fr",{numeric:true,sensitivity:"base"});
}
function clientStatusCounts(rows){
    let free=0,saturated=0,out=0,na=0;
    for(const r of rows){
        const st=getClientPCOStatus(r.pco);
        if(!st.found){na++;continue;}
        if(!st.inside){out++;continue;}
        if(st.occ&&st.occ.state==="PORTS LIBRES")free++;
        else if(st.occ&&st.occ.state==="SATURÉ")saturated++;
        else na++;
    }
    return {free,saturated,out,na};
}
function changerTaillePageClient(value){
    clientPageSize=Math.max(25,Math.min(500,Number(value)||100));
    clientResultPage=0;
    renderClientResultsPage();
}
function exporterResultatsClients(){
    if(!clientResultRows.length)return toast("Aucun résultat à exporter.");
    if(!window.XLSX)return toast("Le module Excel n'est pas disponible.");
    const data=clientResultRows.map(r=>{
        const st=getClientPCOStatus(r.pco);
        const libres=st.found&&st.occ&&st.occ.libres!==null?st.occ.libres:"";
        const vula=!st.found?"PCO NON TROUVÉ":(st.inside?"IN VULA":"OUT VULA");
        const etat=!st.found?"PCO NON TROUVÉ":(!st.inside?"OUT VULA":(st.occ?.state||"—"));
        return {"Nom Client":r.nom,"Adresse Client":r.adresse,"Login":r.login,"Série ONT":r.serie,"ODF":r.odf,"NE":r.ne,"PCO":r.pco,"OLT":r.olt,"Ports libres":libres,"VULA":vula,"État":etat};
    });
    const ws=XLSX.utils.json_to_sheet(data),wb=XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb,ws,"Résultats");
    const now=new Date(),stamp=now.toISOString().slice(0,19).replace(/[T:]/g,"-");
    XLSX.writeFile(wb,`Recherche_clients_${stamp}.xlsx`);
    toast(`${data.length} résultats exportés en Excel.`);
}
async function copierClient(index){
    const r=clientResultRows[index]; if(!r)return;
    const st=getClientPCOStatus(r.pco);
    const libres=st.found&&st.occ&&st.occ.libres!==null?st.occ.libres:"—";
    const vula=!st.found?"PCO NON TROUVÉ":(st.inside?"IN VULA":"OUT VULA");
    const text=`Nom Client: ${r.nom}
Adresse Client: ${r.adresse}
Login: ${r.login}
Série ONT: ${r.serie}
ODF: ${r.odf}
PCO: ${r.pco}
OLT: ${r.olt}
Ports libres: ${libres}
VULA: ${vula}`;
    try{
        await navigator.clipboard.writeText(text);
        toast("Informations client copiées.");
    }catch(e){
        const ta=document.createElement("textarea");ta.value=text;ta.style.position="fixed";ta.style.opacity="0";document.body.appendChild(ta);ta.select();
        try{document.execCommand("copy");toast("Informations client copiées.")}catch(err){toast("Impossible de copier les informations.")}finally{ta.remove()}
    }
}
function renderClientResultsPage(q){
    const box=document.getElementById("clientResults"),stats=document.getElementById("clientStats"),rows=clientResultRows;
    const pageSize=clientPageSize||100,totalPages=Math.max(1,Math.ceil(rows.length/pageSize));
    if(clientResultPage>=totalPages)clientResultPage=totalPages-1;
    const start=clientResultPage*pageSize,end=Math.min(start+pageSize,rows.length),pageRows=rows.slice(start,end);
    if(!rows.length){
        stats.innerHTML="";
        box.innerHTML='<div class="empty">Aucun client trouvé.</div>';
        return;
    }
    const counts=clientStatusCounts(rows);
    stats.innerHTML=`<div class="client-summary">
    <div class="client-stat"><small>RÉSULTATS TROUVÉS</small><strong>${rows.length}</strong></div>
    <div class="client-stat free"><small>IN VULA · PORTS LIBRES</small><strong>${counts.free}</strong></div>
    <div class="client-stat saturated"><small>IN VULA · SATURÉS</small><strong>${counts.saturated}</strong></div>
    <div class="client-stat out"><small>OUT VULA</small><strong>${counts.out}</strong></div>
    </div>
    <div class="client-priority-note"><strong>Priorité :</strong> IN VULA avec ports libres → IN VULA saturés → OUT VULA. Les résultats restent triés selon cette priorité.</div>`;
    let h=`<div class="client-results-head"><div class="client-results-title">Résultats de la recherche · ${start+1}–${end} sur ${rows.length}</div><div class="client-results-tools"><label class="helper">Afficher <select onchange="changerTaillePageClient(this.value)"><option value="100" ${pageSize===100?'selected':''}>100</option><option value="250" ${pageSize===250?'selected':''}>250</option><option value="500" ${pageSize===500?'selected':''}>500</option></select> par page</label><button class="secondary" type="button" onclick="exporterResultatsClients()">📊 Exporter Excel</button></div></div>`;
    h+='<div class="results"><table><thead><tr><th>Nom Client</th><th>Adresse Client</th><th>Login</th><th>Série ONT</th><th>ODF</th><th>PCO</th><th>OLT</th><th>PORTS LIBRES</th><th>VULA</th><th></th></tr></thead><tbody>';
    for(let i=0;i<pageRows.length;i++){
        const r=pageRows[i],globalIndex=start+i;
        const st=getClientPCOStatus(r.pco),vula=st.found?(st.inside?'<span class="badge in">IN VULA</span>':'<span class="occupation-status out">OUT VULA</span>'):'<span class="badge na">PCO NON TROUVÉ</span>';
        const libres=st.found&&st.occ.libres!==null?st.occ.libres:"—";
        const cls=st.found?(st.inside?(st.occ.state==="SATURÉ"?"row-saturated":"row-free"):"row-out"):"row-na";
        h+=`<tr class="${cls}"><td>${escapeHtml(r.nom)}</td><td>${escapeHtml(r.adresse)}</td><td>${escapeHtml(r.login)}</td><td>${escapeHtml(r.serie)}</td><td>${escapeHtml(r.odf)}</td><td><strong>${escapeHtml(r.pco)}</strong></td><td>${escapeHtml(r.olt)}</td><td><strong>${libres}</strong></td><td>${vula}</td><td><button class="secondary client-copy-btn" type="button" title="Copier les informations" onclick="copierClient(${globalIndex})">Copier</button></td></tr>`;
    }
    h+='</tbody></table></div>';
    if(totalPages>1){h+=`<div class="client-pagination"><span class="helper">Affichage ${start+1} à ${end} sur ${rows.length}</span><div class="actions" style="margin-top:0"><button class="secondary" type="button" ${clientResultPage===0?'disabled':''} onclick="clientResultPage--;renderClientResultsPage()">← Précédent</button><span class="helper" style="padding:10px 8px">Page ${clientResultPage+1} / ${totalPages}</span><button class="secondary" type="button" ${clientResultPage===totalPages-1?'disabled':''} onclick="clientResultPage++;renderClientResultsPage()">Suivant →</button></div></div>`;}
    box.innerHTML=h;
}
async function importerListePCOExcel(input){const f=input.files&&input.files[0];if(!f)return;try{showLoading("Lecture de la liste PCO Excel...");const wb=XLSX.read(await f.arrayBuffer(),{type:"array",cellDates:false});const ws=wb.Sheets[wb.SheetNames[0]];const rows=XLSX.utils.sheet_to_json(ws,{defval:"",raw:false});if(!rows.length)throw Error("Le fichier Excel est vide.");const headers=Object.keys(rows[0]);const ph=headers.find(h=>normaliserRechercheClient(h)==="PCO");if(!ph)throw Error('Colonne "PCO" introuvable.');const values=rows.map(r=>String(r[ph]??"").trim()).filter(Boolean);document.getElementById("inputListePCO").value=Array.from(new Set(values)).join("\n");toast(`${values.length} PCO importés dans la liste.`);input.value=""}catch(e){console.error(e);toast(e.message||"Erreur lors de l'import Excel.");input.value=""}finally{hideLoading()}}

let currentPasAPasSessionId=null;

function rechercherClientsAdressePasAPas(address, fallbackAddress=""){
    const wrap=document.getElementById("pasapasClientSearchBox");
    const stats=document.getElementById("pasapasClientStats");
    const box=document.getElementById("pasapasClientResults");

    wrap.style.display="block";
    stats.innerHTML="";
    box.innerHTML="";

    if(!clientRows.length){
        box.innerHTML='<div class="warning"><strong>Base clients non chargée.</strong> Importez la base Excel dans Configuration pour lancer la recherche automatique.</div>';
        return;
    }

    // 1) Première recherche : Province + Commune + Quartier + Voie.
    let searchedAddress=String(address||"").trim();
    let q=normaliserRechercheClient(searchedAddress);
    if(!q){
        box.innerHTML='<div class="empty">Adresse vide : recherche client impossible.</div>';
        return;
    }

    let rows=clientRows
        .filter(r=>r._norm.adresse.includes(q))
        .sort(comparerClientsParVula);

    let usedFallback=false;

    // 2) Si aucun résultat, refaire automatiquement la recherche sans la Voie :
    //    Province + Commune + Quartier.
    const fallback=String(fallbackAddress||"").trim();
    if(!rows.length && fallback){
        const fallbackQ=normaliserRechercheClient(fallback);
        if(fallbackQ && fallbackQ!==q){
            searchedAddress=fallback;
            q=fallbackQ;
            rows=clientRows
                .filter(r=>r._norm.adresse.includes(q))
                .sort(comparerClientsParVula);
            usedFallback=true;
        }
    }

    // Garder les résultats globaux pour Apply Étude / export Excel.
    clientResultRows=rows;
    clientResultPage=0;

    // Afficher dans Recherche Client l'adresse réellement utilisée pour la recherche finale.
    const clientAddressInput=document.getElementById("clientSearchInput");
    if(clientAddressInput)clientAddressInput.value=searchedAddress;

    if(!rows.length){
        stats.innerHTML=`<div class="client-summary"><div class="client-stat"><small>RÉSULTATS TROUVÉS</small><strong>0</strong></div></div>`;
        const fallbackInfo=usedFallback?`<div class="helper" style="margin-top:8px">Deuxième recherche effectuée sans la voie.</div>`:"";
        box.innerHTML=`<div class="empty">Aucun client trouvé pour l’adresse : <strong>${escapeHtml(searchedAddress)}</strong>${fallbackInfo}</div>`;
        return;
    }

    const counts=clientStatusCounts(rows);
    stats.innerHTML=`<div class="client-summary">
      <div class="client-stat"><small>RÉSULTATS TROUVÉS</small><strong>${rows.length}</strong></div>
      <div class="client-stat free"><small>IN VULA · PORTS LIBRES</small><strong>${counts.free}</strong></div>
      <div class="client-stat saturated"><small>IN VULA · SATURÉS</small><strong>${counts.saturated}</strong></div>
      <div class="client-stat out"><small>OUT VULA</small><strong>${counts.out}</strong></div>
    </div>`;

    const maxRows=100;
    const shown=rows.slice(0,maxRows);
    let h=`<div class="client-results-head">
      <div class="client-results-title">Clients trouvés ${usedFallback?"avec Province + Commune + Quartier":"avec l’adresse WimTech complète"} · ${shown.length}${rows.length>maxRows?` sur ${rows.length}`:""}</div>
      <div class="client-results-tools"><button class="secondary" type="button" onclick="exporterResultatsClients()">📊 Exporter Excel</button></div>
    </div>`;
    if(usedFallback){h+=`<div class="notice" style="margin-bottom:12px"><strong>2ᵉ recherche automatique :</strong> aucun résultat avec la voie. Recherche relancée avec <strong>${escapeHtml(searchedAddress)}</strong>.</div>`;}
    h+='<div class="results"><table><thead><tr><th>Nom Client</th><th>Adresse Client</th><th>Login</th><th>Série ONT</th><th>ODF</th><th>PCO</th><th>OLT</th><th>PORTS LIBRES</th><th>VULA</th><th></th></tr></thead><tbody>';

    for(let i=0;i<shown.length;i++){
        const r=shown[i];
        const st=getClientPCOStatus(r.pco);
        const vula=st.found?(st.inside?'<span class="badge in">IN VULA</span>':'<span class="occupation-status out">OUT VULA</span>'):'<span class="badge na">PCO NON TROUVÉ</span>';
        const libres=st.found&&st.occ&&st.occ.libres!==null?st.occ.libres:"—";
        const cls=st.found?(st.inside?(st.occ&&st.occ.state==="SATURÉ"?"row-saturated":"row-free"):"row-out"):"row-na";
        h+=`<tr class="${cls}"><td>${escapeHtml(r.nom)}</td><td>${escapeHtml(r.adresse)}</td><td>${escapeHtml(r.login)}</td><td>${escapeHtml(r.serie)}</td><td>${escapeHtml(r.odf)}</td><td><strong>${escapeHtml(r.pco)}</strong></td><td>${escapeHtml(r.olt)}</td><td><strong>${libres}</strong></td><td>${vula}</td><td><button class="primary client-copy-btn" type="button" onclick="applyEtudePasAPas(${i},this)">Apply Étude</button></td></tr>`;
    }
    h+='</tbody></table></div>';
    if(rows.length>maxRows)h+=`<div class="helper" style="margin-top:10px">${rows.length} résultats trouvés. Les ${maxRows} premiers sont affichés ici. Utilisez Exporter Excel pour récupérer toute la liste.</div>`;
    box.innerHTML=h;
}

async function rechercherAdressePasAPas(){
    const input=document.getElementById("pasapasCmd");
    const cmd=(input.value||"").trim();
    if(!cmd)return toast("Saisissez un numéro CMD.");

    const result=document.getElementById("pasapasResult");
    currentPasAPasSessionId=null;
    try{
        showLoading("Recherche de l’adresse dans WimTech...");
        result.style.display="none";

        const response=await fetch(appUrl("/api/etude-pas-a-pas"),{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({cmd})
        });
        const data=await response.json();

        // CMD introuvable dans WimTech: afficher le résultat et arrêter ici.
        // IMPORTANT: aucune recherche Adresse Client n'est lancée dans ce cas.
        if(data.code==="CMD_NOT_FOUND"){
            const wrap=document.getElementById("pasapasClientSearchBox");
            if(wrap)wrap.style.display="none";
            const stats=document.getElementById("pasapasClientStats");
            const box=document.getElementById("pasapasClientResults");
            if(stats)stats.innerHTML="";
            if(box)box.innerHTML="";

            result.style.display="block";
            result.innerHTML=`
              <div class="result-head">
                <div>
                  <div class="result-title">Étude pas à pas</div>
                  <div class="result-sub">CMD : ${escapeHtml(cmd)}</div>
                </div>
                <div class="big-status out">✕ NON TROUVÉ</div>
              </div>
              <div class="warning" style="margin-top:18px"><strong>cant find cmd</strong></div>`;
            return;
        }

        if(!response.ok || !data.ok)throw Error(data.error||"Recherche impossible.");

        currentPasAPasSessionId=data.session_id||null;
        result.style.display="block";
        result.innerHTML=`
          <div class="result-head">
            <div>
              <div class="result-title">Adresse d'installation</div>
              <div class="result-sub">CMD : ${escapeHtml(cmd)}</div>
            </div>
            <div class="big-status in">✓ TROUVÉE</div>
          </div>
          <div class="data-box" style="margin-top:18px">
            <small>ADRESSE</small>
            <strong style="font-size:17px">${escapeHtml(data.address)}</strong>
          </div>
          <div class="result-data">
            <div class="data-box"><small>Province</small><strong>${escapeHtml(data.province||"—")}</strong></div>
            <div class="data-box"><small>Commune</small><strong>${escapeHtml(data.commune||"—")}</strong></div>
            <div class="data-box"><small>Quartier</small><strong>${escapeHtml(data.quartier||"—")}</strong></div>
            <div class="data-box"><small>Voie</small><strong>${escapeHtml(data.voie||"—")}</strong></div>
          </div>`;

        // Utiliser automatiquement l'adresse WimTech comme entrée de la recherche Adresse Client.
        const clientAddressInput=document.getElementById("clientSearchInput");
        if(clientAddressInput)clientAddressInput.value=data.address||"";
        clientSearchMode="adresse";
        const adresseSansVoie=[data.province,data.commune,data.quartier].filter(Boolean).join(" ").trim();
        rechercherClientsAdressePasAPas(data.address||"",adresseSansVoie);
    }catch(e){
        console.error(e);
        result.style.display="block";
        result.innerHTML=`<div class="warning"><strong>Erreur :</strong> ${escapeHtml(e.message||"Recherche impossible.")}</div>`;
        toast(e.message||"Recherche impossible.");
    }finally{
        hideLoading();
    }
}

async function applyEtudePasAPas(index,button){
    const row=clientResultRows[index];
    if(!row)return toast("Client/PCO introuvable.");
    if(!currentPasAPasSessionId)return toast("Session WimTech non active. Relancez la recherche CMD.");

    const pco=(row.pco||"").trim();
    if(!pco)return toast("Ce client n'a pas de PCO.");

    const parts=pco.split("-").map(x=>x.trim()).filter(Boolean);
    if(parts.length<2)return toast("Format PCO invalide : "+pco);
    const odf=parts[0];
    const zoneReseau=parts.slice(0,-1).join("-");

    const result=document.getElementById("pasapasResult");
    const oldText=button?button.textContent:"";
    if(button){button.disabled=true;button.textContent="Application...";}

    try{
        showLoading(`Application de l'étude sur ${pco}...`);

        // Show exactly what will be sent to WimTech.
        let status=document.getElementById("pasapasApplyStatus");
        if(!status){
            status=document.createElement("div");
            status.id="pasapasApplyStatus";
            status.className="notice";
            status.style.marginTop="14px";
            result.appendChild(status);
        }
        status.innerHTML=`<strong>Apply Étude en cours...</strong><br>ODF : ${escapeHtml(odf)} · Zone Réseau : ${escapeHtml(zoneReseau)} · PCO : ${escapeHtml(pco)}`;

        const response=await fetch(appUrl("/api/apply-etude"),{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({session_id:currentPasAPasSessionId,pco})
        });
        const data=await response.json();
        if(!response.ok || !data.ok)throw Error(data.error||"Apply Étude impossible.");

        if(data.status==="PCO_SATURE"){
            // IMPORTANT: keep currentPasAPasSessionId.
            // Chrome remains open and another Apply Étude button can reuse it.
            status.className="warning";
            status.innerHTML=`<strong>⚠ PCO SATURÉ RÉELLEMENT</strong><br>ODF : ${escapeHtml(data.odf)} · Zone Réseau : ${escapeHtml(data.zone_reseau)} · PCO : ${escapeHtml(data.pco)}<br>Création d'une fibre sans constitution détectée → Annuler cliqué automatiquement.<br><strong>Chrome reste ouvert : vous pouvez tester un autre PCO.</strong>`;
            if(button){button.textContent="PCO saturé";button.disabled=true;}
            toast("PCO saturé réellement. Vous pouvez tester un autre PCO.");
        }else{
            // A successful validation ends the Selenium session.
            currentPasAPasSessionId=null;
            status.className="notice";
            status.innerHTML=`<strong>✓ FINISHED</strong><br>ODF : ${escapeHtml(data.odf)} · Zone Réseau : ${escapeHtml(data.zone_reseau)} · PCO : ${escapeHtml(data.pco)}<br>Étude lancée et validée avec succès.`;
            if(button){button.textContent="✓ Finished";button.disabled=true;}
            toast("Étude terminée et validée.");
        }
    }catch(e){
        console.error(e);
        let status=document.getElementById("pasapasApplyStatus");
        if(status){status.className="warning";status.innerHTML=`<strong>Erreur Apply Étude :</strong> ${escapeHtml(e.message||"Erreur inconnue")}`;}
        if(button){button.disabled=false;button.textContent=oldText||"Apply Étude";}
        toast(e.message||"Apply Étude impossible.");
    }finally{
        hideLoading();
    }
}

function effacerAdressePasAPas(){
    currentPasAPasSessionId=null;
    document.getElementById("pasapasCmd").value="";
    const result=document.getElementById("pasapasResult");
    result.innerHTML="";
    result.style.display="none";
    const wrap=document.getElementById("pasapasClientSearchBox");
    if(wrap)wrap.style.display="none";
    const stats=document.getElementById("pasapasClientStats");
    const box=document.getElementById("pasapasClientResults");
    if(stats)stats.innerHTML="";
    if(box)box.innerHTML="";
}

function escapeHtml(v){return String(v).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#039;")}
window.addEventListener("load",async()=>{try{showLoading("Chargement de la configuration locale...");const found=await loadLocalData();if(dataVULA_Text){try{polygonesVULA=extraireTousLesPolygones(dataVULA_Text)}catch(e){dataVULA_Text=null;polygonesVULA=[]}}chargerIndexOccupationDepuisDonnees();chargerIndexClientsDepuisDonnees();updateConfigUI();toast(found&&dataVULA_Text&&dataPCO_Text&&polygonesVULA.length?"Configuration locale chargée automatiquement.":"Première utilisation : configurez les fichiers VULA et PCO.")}catch(e){console.error(e);toast("Impossible de charger la configuration locale.")}finally{hideLoading()}});
