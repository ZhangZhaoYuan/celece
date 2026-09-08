# JS Inline Script Debugging Reference

## Quick Fix Patterns

### onclick with Single Quote Params
```javascript
// ❌ Wrong (causes Unexpected identifier 'none'):
onclick="zoomImage('' + path + ',')"

// ✅ Correct (use escaped single quotes):
onclick="zoomImage(\\'' + path + '\\',\\'"
```

### Multi-line Function Definition
```javascript
// ❌ Broken (regex newline):
function jsStr(s) { return (s || '').replace(/'/g,"\\'").replace(/\n/g,"\\n").replace(/\n+/g,""); }
/g,""); }

// ✅ Fixed (single line):
function jsStr(s) { return (s || "").replace(/'/g,"\\'").replace(/\n/g,"\\n").replace(/\r/g,""); }
```

### HTML Structure
```html
<!-- All content must be BEFORE </body> -->
<div id="dynamic-panel"></div>
</body>
</html>
```

## Validation Commands

```bash
# JS syntax check
node -e "
const fs = require('fs');
const c = fs.readFileSync('index.html', 'utf-8');
const m = c.match(/<script>([\s\S]*?)<\/script>/);
try { new Function(m[1]); console.log('✓ JS语法正确'); }
catch(e) { console.log('✗', e.message); }
"
```

## Error Pattern Reference

| Error | Cause | Fix |
|-------|-------|-----|
| `Unexpected identifier 'none'` | Quote escaping in string | Use `\\''` for inline onclick |
| `Invalid regular expression: missing /` | Multi-line replace() | Combine to single line |
| `Unexpected token 'catch'` | Missing closing brace | Check brace balance |
| Page blank, no error | DOM not ready | Add DOMContentLoaded check |
