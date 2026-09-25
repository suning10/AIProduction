# State Batching
- React process render(state update) after all event handlers have finished
  - avoid multiple re-render 
- To update a state multiple time in a state (Uncommon) 
  - use setNumber(n => n + 1)
    - pass an updater function 
    - queue it 

```jsx
// this will result 42
export default function Counter() {
  const [number, setNumber] = useState(0);

  return (
    <>
      <h1>{number}</h1>
      <button onClick={() => {
        setNumber(number + 5);
        setNumber(n => n + 1);
        setNumber(42);
      }}>Increase the number</button>
    </>
  )
}
```