Create and update the todo list for work with three or more steps. Do not use it for fewer.
Each item has a content and a status (pending, in_progress, completed).
- Keep exactly one item in_progress while any item is unfinished.
- Mark an item completed as you go. In that same call set the next item in_progress, so there is never zero in_progress while items remain.
- When all items are completed, stop calling tools; another step writes the answer.
- Never put a cargo number or token in an item.
