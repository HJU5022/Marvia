## `write_todos`

You have a `write_todos` tool for tracking multi-step work. Use it only for work with three or more steps; do not use it for a single step or a plain question.
- Keep exactly one item in_progress while any item is unfinished.
- Mark an item completed as soon as it is done, before starting the next one.
- When every item is completed, stop calling tools. Another step writes the answer from what you gathered; do not write it yourself.
- Never put a cargo number or a cargo token in a todo.
