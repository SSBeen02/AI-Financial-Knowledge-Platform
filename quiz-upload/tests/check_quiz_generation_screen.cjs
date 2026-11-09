// UT-QZ-16: render the real quiz.html with controlled API responses.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.QUIZ_TEST_PLAYWRIGHT_PATH || 'playwright');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'verification/quiz-update-2026-11-10');
fs.mkdirSync(out, { recursive: true });
const html = fs.readFileSync(path.join(root, 'quiz.html'), 'utf8');
const questions = [1, 2, 3].map(i => ({question_index: i, question_type: i === 3 ? 'situation' : 'ox',
  prompt: `문제 ${i}`, choices: i === 3 ? ['A','B','C','D'].map(key => ({key,text:key})) : [{key:'O',text:'맞소'},{key:'X',text:'아니오'}]}));
const completed = {id:'screen-test', concept_id:'test-concept', status:'completed', questions};
const results = [];
(async () => {
  const browser = await chromium.launch({headless:true, channel:'chrome'});
  try {
    for (const state of ['failed', 'pending', 'processing', 'completed', 'broken-completed', 'missing-id', 'blank-id']) {
      const page = await browser.newPage({viewport:{width:1100,height:800}});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      let requests = 0;
      await page.route('http://127.0.0.1:18019/**', async route => {
        if (route.request().url().includes('/api/v1/quiz-sets/')) {
          requests++;
          const body = state === 'completed' || (requests > 1 && ['pending','processing'].includes(state))
            ? completed : {...completed, status:state === 'broken-completed' ? 'completed' : state, questions:[]};
          await route.fulfill({json:body});
        } else await route.fulfill({contentType:'text/html; charset=utf-8',body:html});
      });
      await page.goto('http://127.0.0.1:18019/quiz' + (state === 'missing-id' ? '' : state === 'blank-id' ? '?quiz_set_id=%20%20' : '?quiz_set_id=screen-test'));
      if (['missing-id','blank-id'].includes(state)) {
        await page.getByText("퀴즈 정보가 없습니다. 학습 화면에서 '학습 완료'를 눌러 퀴즈를 시작해 주세요.",{exact:true}).waitFor();
        assert.equal(requests,0);
        assert.equal(await page.locator('.choice').count(),0);
        assert.equal(await page.locator('#submit').count(),0);
        assert.deepEqual(errors,[]);
        results.push({state,passed:true,api_requests:requests});
        console.log('PASS',state);
        await page.close();
        continue;
      }
      if (state === 'failed') {
        await page.getByText('퀴즈 생성에 실패했습니다. 학습 화면에서 퀴즈를 다시 요청해 주세요.', {exact:true}).waitFor();
        assert.equal(await page.locator('.choice').count(), 0);
        assert.equal(await page.locator('#submit').count(), 0);
        await page.screenshot({path:path.join(out,'failed-screen.png'),fullPage:true});
      } else if (['pending','processing'].includes(state)) {
        await page.getByText('퀴즈를 준비하는 중입니다. 잠시 후 다시 확인해 주세요.', {exact:true}).waitFor();
        assert.equal(await page.locator('#submit').count(),0);
        await page.getByRole('button',{name:'준비 상태 다시 확인'}).click();
        await page.getByRole('heading',{name:'문제 1',exact:true}).waitFor();
        assert.equal(requests,2);
        assert.equal(await page.locator('.choice').count(),2);
      } else if (state === 'completed') {
        await page.getByRole('heading',{name:'문제 1',exact:true}).waitFor();
        assert.equal(await page.locator('#submit').isDisabled(),true);
        assert.equal(await page.getByRole('button',{name:'X',exact:true}).count(),1);
        await page.getByRole('button',{name:'O',exact:true}).click();
        assert.equal(await page.locator('#submit').isEnabled(),true);
        await page.locator('#submit').click();
        await page.getByRole('heading',{name:'문제 2',exact:true}).waitFor();
      } else {
        await page.getByText('퀴즈 문제를 확인할 수 없습니다. 학습 화면에서 다시 확인해 주세요.',{exact:true}).waitFor();
        assert.equal(await page.locator('#submit').count(),0);
      }
      assert.deepEqual(errors,[]);
      results.push({state,passed:true,uncaught_errors:errors});
      console.log('PASS',state);
      await page.close();
    }
    fs.writeFileSync(path.join(out,'screen-results.json'),JSON.stringify({scope:'headless Chrome; actual quiz.html; mocked API responses',results},null,2));
  } finally {await browser.close();}
})().catch(e => {console.error(e);process.exitCode=1;});
