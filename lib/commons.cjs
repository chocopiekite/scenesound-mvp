function safeUrl(value,host){try{const u=new URL(value);return u.protocol==='https:'&&u.hostname===host&&!u.username&&!u.password?u.href:null;}catch{return null;}}
function plain(value){return String(value||'').replace(/<[^>]*>/g,'').replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/\s+/g,' ').trim().slice(0,250);}
async function search(query,page=1){
 const url=new URL('https://commons.wikimedia.org/w/api.php');url.search=new URLSearchParams({action:'query',format:'json',generator:'search',gsrsearch:query+' filetype:audio',gsrnamespace:'6',gsrlimit:'12',gsroffset:String((page-1)*12),prop:'imageinfo',iiprop:'url|size|mime|metadata|extmetadata',iiextmetadatafilter:'License|LicenseShortName|LicenseUrl|Artist|Categories|ImageDescription|Restrictions',maxlag:'5'});
 const response=await fetch(url,{headers:{'User-Agent':'SceneSoundMVP/1.0 (https://scenesound-mvp.vercel.app/)'},signal:AbortSignal.timeout(12000)});if(!response.ok)throw Error('Commons unavailable');
 const data=await response.json();if(data.error)throw Error('Commons query failed');if(data.query?.pages&&!Object.values(data.query.pages).every(p=>p&&typeof p==='object'))throw Error('Invalid response');
 return Object.values(data.query?.pages||{}).sort((a,b)=>(a.index||0)-(b.index||0)).flatMap(file=>{
  const info=file.imageinfo?.[0],meta=info?.extmetadata||{};if(!info||!Number.isSafeInteger(file.pageid)||file.pageid<1||!['audio/ogg','application/ogg','audio/mpeg','audio/wav','audio/x-wav','audio/flac'].includes(info.mime)||!Number.isFinite(info.size)||info.size>20*1024*1024)return [];
  if(/pronunciation|audio file for the .*word/i.test((meta.Categories?.value||'')+' '+(meta.ImageDescription?.value||''))||plain(meta.Restrictions?.value))return [];
  const duration=Number(info.metadata?.find(m=>m.name==='length'||m.name==='playtime_seconds')?.value);if(!Number.isFinite(duration)||duration<=0||duration>900)return [];
  const preview=safeUrl(info.url,'upload.wikimedia.org'),source=safeUrl(info.descriptionurl,'commons.wikimedia.org');if(!preview||!source)return [];
  const licenseCode=meta.License?.value;let license,licenseUrl;
  if(licenseCode==='cc0'){license='CC0';licenseUrl='https://creativecommons.org/publicdomain/zero/1.0/';}
  else if(licenseCode==='pd'&&meta.LicenseShortName?.value==='Public domain'){license='퍼블릭 도메인';licenseUrl=source;}
  else if(/^cc-by-(3\.0|4\.0)$/.test(licenseCode||'')){license='CC BY '+licenseCode.slice(6)+' · 출처 표시';licenseUrl=safeUrl(String(meta.LicenseUrl?.value||'').replace(/^http:/,'https:'),'creativecommons.org');if(!licenseUrl||!/^https:\/\/creativecommons.org\/licenses\/by\/(3\.0|4\.0)\/?$/.test(licenseUrl))return [];}
  else return [];
  const creator=plain(meta.Artist?.value);if(!creator)return [];
  return [{id:file.pageid,name:plain(file.title?.replace(/^File:/,'')),creator,duration,preview,source,license,licenseUrl,provider:'commons',library:'Wikimedia Commons'}];
 }).slice(0,3);
}
module.exports={search};
