#!/usr/bin/env node
/**
 * Markdown → PDF 转换脚本
 * 
 * 流水线：marked(解析) → puppeteer(Chrome渲染) → page.pdf(输出)
 * 品质：浏览器级渲染，emoji/表格/列表完美，支持 HarmonyOS Sans 等中文字体
 * 
 * 用法:
 *   node scripts/md2pdf.js input.md output.pdf [style.css]
 * 
 * 前置依赖:
 *   npm install puppeteer-core marked
 *   apt-get install google-chrome-stable
 * 
 * 风格 CSS: references/pdf-chrome-print.css
 */

const puppeteer = require('puppeteer-core');
const { marked } = require('marked');
const fs = require('fs');

async function md2pdf(mdPath, pdfPath, cssPath) {
  const md = fs.readFileSync(mdPath, 'utf-8');

  // Fix list formatting: 在列表前补空行（pandoc 需要空行才识别列表，
  // marked 也推荐有空行，这里做兼容预处理）
  const lines = md.split('\n');
  const fixedLines = [];
  let inList = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trimEnd();
    const isList = /^[-*+]\s/.test(trimmed) ||
                   /^[-*+]\s\[[ x]?\]/.test(trimmed);
    if (isList && !inList && i > 0) {
      const prev = lines[i - 1].trimEnd();
      if (prev !== '' && !/^[-*+]\s/.test(prev) && !/^[-*+]\s\[[ x]?\]/.test(prev)) {
        fixedLines.push('');
      }
    }
    inList = isList;
    fixedLines.push(line);
  }
  const fixedMd = fixedLines.join('\n');

  // 用 marked 解析 markdown（比 pandoc 更宽容的列表解析）
  const css = fs.readFileSync(cssPath, 'utf-8');
  const bodyHtml = marked.parse(fixedMd, { breaks: false, gfm: true });
  const html = `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>${css}</style>
</head><body>${bodyHtml}</body></html>`;

  // Chrome headless 渲染
  const browser = await puppeteer.launch({
    executablePath: '/usr/bin/google-chrome-stable',
    args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
    headless: true,
  });
  const page = await browser.newPage();
  await page.setContent(html, { waitUntil: 'networkidle0', timeout: 15000 });
  await page.pdf({
    path: pdfPath,
    format: 'A4',
    margin: { top: '15mm', right: '20mm', bottom: '15mm', left: '20mm' },
    printBackground: true,
    displayHeaderFooter: false,
    preferCSSPageSize: true,
  });
  await browser.close();
  console.log(`PDF written: ${pdfPath}  (${Math.round(fs.statSync(pdfPath).size / 1024)} KB)`);
}

// CLI 入口
const mdPath = process.argv[2];
const pdfPath = process.argv[3];
const cssPath = process.argv[4] || __dirname + '/../references/pdf-chrome-print.css';

if (!mdPath || !pdfPath) {
  console.error('用法: node scripts/md2pdf.js input.md output.pdf [style.css]');
  process.exit(1);
}
md2pdf(mdPath, pdfPath, cssPath).catch(err => {
  console.error('转换失败:', err.message);
  process.exit(1);
});
