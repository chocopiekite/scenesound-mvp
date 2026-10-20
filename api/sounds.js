const CC0 = 'https://creativecommons.org/publicdomain/zero/1.0/';
function safeUrl(value, hosts) {
  try {const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password&&hosts.includes(url.hostname)?url.href:null;}catch{return null;}
}
module.exports=async function sounds(req,res){
  res.setHeader('Cache-Control','no-store');
  const reply=(status,data)=>res.status(status).json(data);
  if(req.method!=='GET'){res.setHeader('Allow','GET');return reply(405,{error:'지원하지 않는 요청이에요.'});}
  const query=new URL(req.url,'http://localhost').searchParams.get('q')?.trim();
  if(!query||query.length>100||!/[a-zA-Z가-힣]/.test(query))return reply(400,{error:'찾을 소리 이름을 확인해 주세요.'});
  if(!process.env.FREESOUND_API_KEY)return reply(503,{error:'미리 듣기 연결을 준비 중이에요. 추천 목록은 그대로 이용할 수 있어요.'});
  try {
    const url=new URL('https://freesound.org/apiv2/search/');
    url.search=new URLSearchParams({query,filter:'license:"Creative Commons 0"',fields:'id,name,username,license,duration,previews,url',page_size:'9',group_by_pack:'1'}).toString();
    const response=await fetch(url,{headers:{Authorization:'Token '+process.env.FREESOUND_API_KEY},signal:AbortSignal.timeout(12000)});
    if(!response.ok)return reply(response.status===429?429:502,{error:response.status===429?'소리 검색이 잠시 몰렸어요. 조금 뒤 다시 눌러 주세요.':'소리를 불러오지 못했어요. 잠시 후 다시 눌러 주세요.'});
    const data=await response.json();
    if(!Array.isArray(data.results))return reply(502,{error:'소리 검색 결과를 확인하지 못했어요.'});
    const candidates=data.results.flatMap(sound=>{
      const license=safeUrl(typeof sound.license==='string'?sound.license.replace(/^http:\/\//,'https://'):'',['creativecommons.org']);
      if(license!==CC0||!Number.isSafeInteger(sound.id)||sound.id<=0||typeof sound.name!=='string'||typeof sound.username!=='string'||!Number.isFinite(sound.duration)||sound.duration<=0)return [];
      const preview=safeUrl(sound.previews?.['preview-hq-mp3']||sound.previews?.['preview-lq-mp3'],['cdn.freesound.org','freesound.org']);
      const source=safeUrl(sound.url,['freesound.org','www.freesound.org']);
      if(!preview||!source)return [];
      return [{id:sound.id,name:sound.name.slice(0,200),creator:sound.username.slice(0,100),duration:sound.duration,license:'CC0',licenseUrl:CC0,preview,source}];
    }).slice(0,3);
    return reply(200,{candidates});
  }catch(error){return reply(error.name==='TimeoutError'?504:502,{error:'소리 검색이 지연되고 있어요. 잠시 후 다시 눌러 주세요.'});}
};
