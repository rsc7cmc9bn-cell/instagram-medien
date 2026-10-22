// Holt den Objektbestand von immobilien-britta-niessen.de (gerendert, inkl. JS) für den Abgleich der Instagram-Inhalte.
// Läuft in GitHub Actions, weil die Claude-Umgebung die Domain nicht erreicht. Ergebnis: website/ im Branch website-daten.
const { chromium } = require('playwright');
const fs = require('fs');
const START = 'https://immobilien-britta-niessen.de/';
(async () => {
  fs.mkdirSync('website/seiten', { recursive: true });
  fs.mkdirSync('website/xhr', { recursive: true });
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1400, height: 1000 } });
  let n = 0;
  ctx.on('response', async r => {
    const ct = r.headers()['content-type'] || '';
    if (ct.includes('json')) {
      try { fs.writeFileSync(`website/xhr/${String(++n).padStart(3, '0')}.json`, JSON.stringify({ url: r.url(), body: await r.json() }, null, 1)); } catch (e) {}
    }
  });
  const p = await ctx.newPage();
  const save = async (name) => {
    fs.writeFileSync(`website/seiten/${name}.html`, await p.content());
    fs.writeFileSync(`website/seiten/${name}.txt`, await p.evaluate(() => document.body.innerText));
    await p.screenshot({ path: `website/seiten/${name}.png`, fullPage: true });
  };
  await p.goto(START, { waitUntil: 'networkidle', timeout: 60000 });
  for (let i = 0; i < 12; i++) { await p.mouse.wheel(0, 1500); await p.waitForTimeout(500); }
  await p.waitForTimeout(2000);
  await save('start');
  const links = [...new Set(await p.$$eval('a[href]', as => as.map(a => a.href)))];
  fs.writeFileSync('website/links.json', JSON.stringify(links, null, 1));
  const host = new URL(START).host;
  const ziel = links.filter(u => !u.startsWith('mailto:') && !u.startsWith('tel:') && !u.includes('#') &&
    (/expose|immobilie|objekt|angebot|verkauf|referenz|propstack/i.test(u)) && (u.includes(host) || /propstack/.test(u))).slice(0, 60);
  let i = 0;
  for (const u of ziel) {
    try {
      await p.goto(u, { waitUntil: 'networkidle', timeout: 45000 });
      await p.waitForTimeout(1000);
      await save(`objekt-${String(++i).padStart(2, '0')}`);
      fs.appendFileSync('website/objektseiten.txt', `objekt-${String(i).padStart(2, '0')}\t${u}\n`);
    } catch (e) { fs.appendFileSync('website/fehler.txt', `${u}\t${e.message}\n`); }
  }
  await b.close();
})();
