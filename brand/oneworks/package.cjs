// Mechanical packaging only. All character paths are untouched OneWorks output.
// NODE_PATH=/path/to/node_modules node brand/oneworks/package.cjs
const fs = require('node:fs');
const path = require('node:path');
const sharp = require('sharp');
const root = __dirname;
const parameters = JSON.parse(fs.readFileSync(path.join(root, 'parameters.json'), 'utf8'));
const output = path.join(root, 'exports');
fs.mkdirSync(output, {recursive:true});
const sizes = [16,32,64,128,512,1024];
(async () => {
  let links = '# 可重现编辑链接\n\n';
  const cells = [];
  let x = 0;
  for (const [key, candidate] of Object.entries(parameters.candidates)) {
    const url = new URL(parameters.tool);
    for (const [name, value] of Object.entries({...parameters.common, ...candidate})) {
      if (name !== 'title') url.searchParams.set(name, Array.isArray(value) ? JSON.stringify(value) : String(value));
    }
    url.hash = '/editor';
    links += `- [${candidate.title}](${url.toString()})\n`;
    const raw = fs.readFileSync(path.join(root, 'originals', `${key}.svg`), 'utf8');
    const geometry = raw.replace(/^<svg[^>]*>/,'').replace(/<\/svg>\s*$/,'');
    const wrapper = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 420" width="1024" height="1024">';
    const transparent = wrapper + geometry + '</svg>';
    // Match the neutral camera background; no second icon mask is applied at integration.
    const icon = wrapper + '<rect width="420" height="420" rx="26" fill="#f2f0eb"/>' + geometry + '</svg>';
    fs.writeFileSync(path.join(output, `${key}-transparent.svg`), transparent);
    fs.writeFileSync(path.join(output, `${key}-icon.svg`), icon);
    await sharp(Buffer.from(transparent)).png().toFile(path.join(output, `${key}-transparent.png`));
    for (const size of sizes) {
      await sharp(Buffer.from(icon)).resize(size,size).png().toFile(path.join(output, `${key}-${size}.png`));
    }
    for (const [j,bg] of ['#faf9f6','#161b1a'].entries()) {
      cells.push({input:await sharp({create:{width:500,height:520,channels:4,background:bg}}).png().toBuffer(),left:x,top:j*520});
      cells.push({input:await sharp(Buffer.from(transparent)).resize(330,330).png().toBuffer(),left:x+85,top:j*520+20});
      for (const [i,size] of [16,32,64,128].entries()) {
        cells.push({input:await sharp(Buffer.from(icon)).resize(size,size).png().toBuffer(),left:x+28+i*112,top:j*520+355+(128-size)/2});
      }
    }
    x += 500;
  }
  fs.writeFileSync(path.join(root, 'editor-links.md'), links);
  await sharp({create:{width:1000,height:1040,channels:4,background:'#f2f0eb'}}).composite(cells).png().toFile(path.join(output,'comparison.png'));
})();
