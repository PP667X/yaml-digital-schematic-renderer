const fs = require('fs');
const ELK = require('elkjs/lib/elk.bundled.js');
const graph = JSON.parse(fs.readFileSync(0, 'utf8'));
new ELK().layout(graph).then(result => {
  process.stdout.write(JSON.stringify(result));
}).catch(error => { console.error(error); process.exitCode = 1; });
