## what is state 

- live inside the component


State vs Context API
- state can result in props drilling 
  - the component need it down the road 
  - all the component in between have to carry extra prop to pass
- context api is in global level 
  - best for themes, auth and lang
```markdown

State	Context
Scope	Local to one component	Global to a subtree
Access	Pass via props	Any child can grab it
Best for	UI state, form inputs	Themes, auth, language
Re-renders	Only that component + children via props	ALL consumers re-render on change
Complexity	Simple	More setup needed
```
Decision 
```markdown
Local UI state (open/closed, input value)
→ useState

Shared between a few nearby components
→ Lift state up + props

Needed by many components far apart (theme, auth, language)
→ Context API

Complex global state with many actions
→ Redux / Zustand (third party)
```