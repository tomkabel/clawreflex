// Log the rig's Chrome profile into the stage Control UI (headless), then close cleanly so the
// app window rig.py opens next is already signed in. The token stays out of every URL bar.
// node clawreflex/rig-chrome.mjs <stage dir>
import fs from 'fs';
import { launch } from '../tools/chrome.mjs';

const stage = process.argv[2];
const token = fs.readFileSync(`${stage}/gwtoken`, 'utf8').trim();
const port = JSON.parse(fs.readFileSync(`${stage}/openclaw.json`, 'utf8')).gateway.port;
const browser = await launch({ userDataDir: `${stage}/chrome-profile` });
const page = await browser.newPage();
await page.goto(`http://127.0.0.1:${port}/#token=${token}&gatewayUrl=ws%3A%2F%2F127.0.0.1%3A${port}`, { waitUntil: 'networkidle2' });
await new Promise(r => setTimeout(r, 4000));
await page.goto(`http://127.0.0.1:${port}/chat/main`, { waitUntil: 'networkidle2' });
await new Promise(r => setTimeout(r, 3000));
const text = await page.evaluate(() => document.body.innerText);
await browser.close();
if (/Conversation unavailable/.test(text)) { console.error('login failed'); process.exit(1); }
console.log('logged in');
