https://react.dev/learn#displaying-data

# Summary
- curly brace [curly brace](#curly-braces-)
- display data [display](#display-data-)
- conditional render [conditional](#conditional-render)
- render list [render list](#render-list-)
- respond to event [respond to event](#respond-to-event)
- update screen [update screen](#update-screen---usestate)

## curly braces 

- jsx 
  - used to add markup into javascript
  - Curly braces allow escape back to javascript 

## display data 

```jsx
return (
  <h1>
    {user.name}
  </h1>
);

alt={'Photo of ' + user.name}
```

## conditional Render
```jsx
<div>
  {isLoggedIn ? (
    <AdminPanel />
  ) : (
    <LoginForm />
  )}
</div>
```
## render list 
use for loop and map.\
note that the inside \<li> need a key

```jsx
const products = [
  { title: 'Cabbage', isFruit: false, id: 1 },
  { title: 'Garlic', isFruit: false, id: 2 },
  { title: 'Apple', isFruit: true, id: 3 },
];

export default function ShoppingList() {
  const listItems = products.map(product =>
    <li
      key={product.id}
      style={{
        color: product.isFruit ? 'magenta' : 'darkgreen'
      }}
    >
      {product.title}
    </li>
  );

  return (
    <ul>{listItems}</ul>
  );
}
```

## respond to event
use event handler, **function name only, infinite loop if add ()**
```jsx
function MyButton() {
  function handleClick() {
    alert('You clicked me!');
  }

  return (
    <button onClick={handleClick}>
      Click me
    </button>
  );
}
```

## Update Screen - useState
### two steps
- similar to vue 
  - immutable(optional) + setter
  - useState is local 
```jsx
import { useState } from 'react';
function MyButton() {
  const [count, setCount] = useState(0);}
```
```jsx
function MyButton() {
  const [count, setCount] = useState(0);

  function handleClick() {
    setCount(count + 1);
  }

  return (
    <button onClick={handleClick}>
      Clicked {count} times
    </button>
  );
}
```
