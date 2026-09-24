# Props Basic
- Pass data from parent to child 

### pass data 
```jsx
function Square({ value }) {
  return <button className="square">{value}</button>;
}

export default function Board() {
  return (
    <>
        <Square value="1" />
        <Square value="2" />
    </>)
}
```