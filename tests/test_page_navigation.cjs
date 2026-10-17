// Presentation contract: no API calls or data replacement when navigating pages.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map();
function element(selector){
  if(!elements.has(selector)){
    const classes=new Set(),attributes={};
    elements.set(selector,{value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,checked:false,dataset:{},children:[],attributes,
      classList:{add:n=>classes.add(n),remove:n=>classes.delete(n),contains:n=>classes.has(n),toggle(n){if(classes.has(n)){classes.delete(n);return false;}classes.add(n);return true;}},
      append(...nodes){for(const node of nodes){if(node.parent)node.parent.children=node.parent.children.filter(x=>x!==node);this.children.push(node);node.parent=this;}},
      querySelector:s=>element(selector+' '+s),setAttribute:(k,v)=>attributes[k]=v,removeAttribute:k=>delete attributes[k],focus(){this.focused=true;},scrollIntoView(){},scrollTo(){},showModal(){},close(){}});
  }return elements.get(selector);
}
const links=['home','upload','review','results','profile'].map(name=>{const link=element('nav-'+name);link.dataset.page=name;return link;});
const listeners={},requests=[];
const document={querySelector:element,getElementById:id=>element('#'+id),querySelectorAll:s=>s==='.page-nav [data-page]'?links:[],createElement:()=>({}),addEventListener:(n,fn)=>listeners[n]=fn,body:element('body')};
const ctx={console,document,setTimeout,clearTimeout,URL,Blob,AbortController,location:{hash:''},history:{replaceState(a,b,hash){ctx.location.hash=hash;}},MutationObserver:class{observe(){}},window:{addEventListener(){},scrollTo(){}},fetch:async path=>{requests.push(path);return {json:async()=>({token:'test'})};}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('static/app.js','utf8'),ctx);
const run=s=>vm.runInContext(s,ctx),ui=ctx.window.runflowUI;
assert(ui);assert.equal(element('#homePage').hidden,false);assert.equal(element('#photoStep').hidden,true);
const initialRequests=requests.length,age=element('#ageYears');age.value='32';
run("basket=[{name:'선택한 약',code:'1'}];photoGroups=[{id:7,status:'choice',filename:'사진',result:{candidates:[]}}]");
for(const route of ['upload','profile','review','results','home','review'])assert.equal(ui.navigate(route),true);
assert.equal(requests.length,initialRequests,'페이지 전환은 API 요청을 만들지 않음');
assert.equal(element('#ageYears'),age);assert.equal(age.value,'32');assert.equal(run('basket[0].name'),'선택한 약');assert.equal(run('photoGroups[0].id'),7);
assert(element('#profilePage').children.includes(element('#userProfileDialog .user-profile')),'필드는 복제가 아닌 이동');
assert.equal(links[2].attributes['aria-current'],'page');
ui.navigate('results');assert.equal(element('#emptyResults').hidden,false);assert.equal(element('#resultStep').hidden,true);
run('lastReport={}');ui.sync();assert.equal(element('#emptyResults').hidden,true);assert.equal(element('#resultStep').hidden,false);
run('invalidate()');ui.sync();assert.equal(element('#emptyResults').hidden,false);assert.match(element('#emptyResultHelp').textContent,/변경/);
run('busy=true');ui.sync();assert.equal(element('#workProgress').hidden,false);assert.equal(ui.navigate('upload'),false);run('busy=false');ui.sync();assert.equal(element('#workProgress').hidden,true);
element('#menuToggle').onclick();assert.equal(element('#menuToggle').attributes['aria-expanded'],'true');listeners.keydown({key:'Escape'});assert.equal(element('#menuToggle').attributes['aria-expanded'],'false');
run("photoGroups=[{id:1,status:'applied',filename:'완료'},{id:2,status:'choice',filename:'선택',result:{candidates:[]}}];renderBatchQueue()");
assert(element('#batchChoices').innerHTML.indexOf('선택')<element('#batchChoices').innerHTML.indexOf('완료'),'선택 필요 항목 우선 표시');assert.equal(run('photoGroups[0].id'),1,'원본 순서는 유지');
const html=fs.readFileSync('static/index.html','utf8'),ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(x=>x[1]);assert.equal(new Set(ids).size,ids.length,'ID 중복 없음');
console.log('PASS: 페이지 이동·입력/제품 보존·빈 결과·결과 무효화·진행 상태·모바일 메뉴·후보 우선 표시');
