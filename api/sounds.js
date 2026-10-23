const freesound=require('../lib/freesound.cjs');
const epidemic=require('../lib/epidemic.cjs');
module.exports=async(req,res)=>{
 res.setHeader('Cache-Control','no-store');
 const reply=(status,data)=>res.status(status).json(data);
 if(req.method!=='GET')return reply(405,{error:'지원하지 않는 요청이에요.'});
 const params=new URL(req.url,'http://localhost').searchParams;
 const local=epidemic.localPrototype(req), es=epidemic.enabled(req), fs=Boolean(process.env.FREESOUND_API_KEY)||(local&&process.env.FREESOUND_PRODUCTION_PROXY==='true');
 if(params.get('providers')==='1')return reply(200,{freesound:fs,epidemic:es,prototype:local});
 const query=params.get('q')?.trim(),provider=params.get('provider')||'all';
 if(!query||query.length>100||!/[a-zA-Z가-힣]/.test(query)||!['all','freesound','epidemic'].includes(provider))return reply(400,{error:'찾을 소리 이름과 라이브러리를 확인해 주세요.'});
 if(provider==='epidemic'&&!es)return reply(503,{error:'Epidemic Sound는 API 키가 연결된 로컬 시험 화면에서만 이용할 수 있어요.'});
 if(!fs&&!es)return reply(503,{error:'미리 듣기 연결을 준비 중이에요. 추천 목록은 그대로 이용할 수 있어요.'});
 const jobs=[];
 if(provider!=='epidemic'&&fs)jobs.push((async()=>{
  if(!process.env.FREESOUND_API_KEY){const r=await fetch('https://scenesound-mvp.vercel.app/api/sounds?q='+encodeURIComponent(query)+'&provider=freesound',{signal:AbortSignal.timeout(15000)});if(!r.ok)throw Error('Freesound');return{provider:'freesound',...(await r.json())};}
  let code,data;await freesound(req,{setHeader(){},status(c){code=c;return this;},json(d){data=d;}});if(code!==200){const e=new Error(data?.error);e.status=code;throw e;}return{provider:'freesound',...data};
 })());
 if(provider!=='freesound'&&es)jobs.push(epidemic.search(query,req).then(candidates=>({provider:'epidemic',candidates})));
 const results=await Promise.allSettled(jobs),candidates=[],warnings=[];
 for(const result of results){if(result.status==='fulfilled')candidates.push(...result.value.candidates.map(c=>({...c,provider:result.value.provider,library:result.value.provider==='epidemic'?'Epidemic Sound':'Freesound'})));else warnings.push('일부 라이브러리에 연결하지 못했어요. 잠시 후 다시 찾아 주세요.');}
 if(!results.some(r=>r.status==='fulfilled')){const status=results.find(r=>r.status==='rejected')?.reason.status;return reply(status===429?429:502,{error:status===429?'소리 검색이 잠시 몰렸어요. 조금 뒤 다시 눌러 주세요.':'소리를 불러오지 못했어요. 잠시 후 다시 눌러 주세요.'});}
 return reply(200,{candidates,warnings});
};
