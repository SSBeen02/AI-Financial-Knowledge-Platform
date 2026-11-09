const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.QUIZ_TEST_PLAYWRIGHT_PATH||'playwright');
const root=path.resolve(__dirname,'..');
const out=path.join(root,'verification/quiz-requirements-2026-11-10');
const html=fs.readFileSync(path.join(root,'quiz.html'),'utf8');
const origin='http://127.0.0.1:18021';
const questions=[1,2,3].map(i=>({question_index:i,question_type:i===3?'situation':'ox',prompt:`문제 ${i}`,choices:(i===3?['A','B','C','D']:['O','X']).map(key=>({key,text:key}))}));
const quiz={id:'restore-test',concept_id:'same-concept',stage_id:'stage1',learning_session_id:'session',status:'completed',questions};
const results=[];
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const payloads=[];
  let reject=true;
  await page.route(origin+'/**',async route=>{
   const req=route.request();
   if(req.url().endsWith('/submit')){
    payloads.push(JSON.parse(req.postData()));
    if(reject){await route.fulfill({status:503,json:{message:'시험용 저장 실패'}});return;}
    await route.fulfill({json:{submission_id:'first',correct_count:0,is_passed:false,results:questions.map(q=>({...q,submitted_answer:'X',answer:q.question_type==='ox'?'O':'A',is_correct:false,explanation:'해설이오.'}))}});
   }else if(req.url().includes('/api/v1/quiz-sets/')) await route.fulfill({json:quiz});
   else await route.fulfill({contentType:'text/html; charset=utf-8',body:html});
  });
  await page.goto(origin+'/quiz?quiz_set_id=restore-test');
  await page.getByRole('button',{name:'X',exact:true}).click();
  await page.locator('#submit').click();
  await page.getByRole('heading',{name:'문제 2',exact:true}).waitFor();
  await page.getByRole('button',{name:'O',exact:true}).click();
  await page.reload();
  await page.getByRole('heading',{name:'문제 2',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'O',exact:true}).getAttribute('aria-pressed'),'true');
  assert.equal(await page.evaluate(()=>JSON.parse(sessionStorage.getItem('quiz-draft-v1:restore-test')).answers['1']),'X');
  results.push({case:'reload_preserves_answers_and_position',passed:true});
  await page.locator('#submit').click();
  await page.getByRole('button',{name:'B',exact:true}).click();
  await page.locator('#submit').click();
  await page.getByText('시험용 저장 실패',{exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'B',exact:true}).getAttribute('aria-pressed'),'true');
  await page.reload();
  await page.getByRole('heading',{name:'문제 3',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'B',exact:true}).getAttribute('aria-pressed'),'true');
  reject=false;
  await page.locator('#submit').click();
  await page.getByText('아직 통과하지 못했습니다.',{exact:true}).waitFor();
  assert.deepEqual(payloads[0],payloads[1]);
  assert.equal(await page.evaluate(()=>sessionStorage.getItem('quiz-draft-v1:restore-test')),null);
  results.push({case:'failed_submit_preserves_draft_and_retry_key_then_clears_on_success',passed:true});
  const link=new URL(await page.getByRole('link',{name:'재학습하러 가기'}).getAttribute('href'),origin);
  assert.equal(link.searchParams.get('concept_id'),'same-concept');
  assert.equal(link.searchParams.get('stage_id'),'stage1');
  results.push({case:'relearning_link_carries_concept_and_stage',passed:true});
  await page.evaluate(()=>sessionStorage.setItem('quiz-draft-v1:restore-test','bad-json'));
  await page.reload();
  await page.getByRole('heading',{name:'문제 1',exact:true}).waitFor();
  assert.deepEqual(errors,[]);
  results.push({case:'corrupt_draft_does_not_break_page',passed:true});
  await page.addInitScript(()=>window.quizLearningDestinationProvider=({concept_id})=>'/chat?concept_id='+encodeURIComponent(concept_id));
  await page.reload();
  for(const key of ['O','X','A']){
   await page.getByRole('button',{name:key,exact:true}).click();
   await page.locator('#submit').click();
  }
  await page.getByRole('link',{name:'재학습하러 가기'}).waitFor();
  assert.equal(new URL(await page.getByRole('link',{name:'재학습하러 가기'}).getAttribute('href')).pathname,'/chat');
  results.push({case:'integration_destination_hook_is_used',passed:true});
  fs.mkdirSync(out,{recursive:true});
  fs.writeFileSync(path.join(out,'restoration-results.json'),JSON.stringify({scope:'actual HTML; mocked APIs; sessionStorage; not deployed chatbot',results},null,2));
  for(const row of results) console.log('PASS',row.case);
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
