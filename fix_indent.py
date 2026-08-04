with open('D:/小赛助手/backend/main.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Fix the 8-space indentation to 4-space in the effective scripts block
# Replace all occurrences of 8-space leading indent with 4-space
lines = text.split('\n')
fixed = []
in_block = False
for i, line in enumerate(lines):
    # Detect the start of the effective refs block
    if 'effective_refs = []' in line and line.startswith('        '):
        in_block = True
    # Fix indentation when in block
    if in_block:
        # Count leading spaces
        stripped = line.lstrip(' ')
        leading = len(line) - len(stripped)
        if leading > 0 and leading % 4 == 0:
            # Reduce by one level (4 spaces)
            new_leading = leading - 4
            line = ' ' * new_leading + stripped
    # Detect end of block
    if in_block and line.strip().startswith('result = await generate_script('):
        in_block = False

text = '\n'.join(lines)

with open('D:/小赛助手/backend/main.py', 'w', encoding='utf-8') as f:
    f.write(text)

import py_compile
try:
    py_compile.compile('D:/小赛助手/backend/main.py', doraise=True)
    print('✅ main.py OK')
except py_compile.PyCompileError as e:
    print('❌', e)