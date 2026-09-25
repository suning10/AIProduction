# State

## Summary

- why local variable is not enough 
  - React don't persist between renders
  - does not realize it needs to render again with new data
- useStaste is a hook
  - usexxx is a hook
  - update -> remember -> render
- state is fully isolated 
  - change one won't change another 
- https://react.dev/learn/state-a-components-memory

## 3 steps
- Trigger
  - Init
  - StateChange
- Render
  - must be pure
  - change variable outside is an impure
- Commit 
  - call append child on ini
  - will apply the minimal change


### more on pure
- It minds its own business. It should not change any objects or variables that existed before rendering.
- Same inputs, same output. Given the same inputs, a component should always return the same JSX.

### commit-minimal-change
```jsx
// only time change, change in text
export default function Clock({ time }) {
  return (
    <>
      <h1>{time}</h1>
      <input />
    </>
  );
}
```

### impure function
```jsx
let guest = 0;

function Cup() {
  // Bad: changing a preexisting variable!
  guest = guest + 1;
  return <h2>Tea cup for guest #{guest}</h2>;
}

export default function TeaSet() {
  return (
    <>
      <Cup />
      <Cup />
      <Cup />
    </>
  );
}

```