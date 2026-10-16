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

### more example
```jsx
export default function ({data, referesh, user}):{
    data: Dashboard
    refresh
}

// from admin
<DeptPanel data={data} refresh={refresh} user={user} />
```