# Event



## Event Handler
### read props in event handler
- use {props} to pass data from parent to child
```jsx
function Button({ onClick, children }) {
  return (
    <button onClick={e => {
      e.stopPropagation();
      onClick();
    }}>
      {children}
    </button>
  );
}

export default function Toolbar() {
  return (
    <div className="Toolbar" onClick={() => {
      alert('You clicked on the toolbar!');
    }}>
      <Button onClick={() => alert('Playing!')}>
        Play Movie
      </Button>
      <Button onClick={() => alert('Uploading!')}>
        Upload Image
      </Button>
    </div>
  );
}
```

### pass function (event handler) as props
- similar to props 
- event handler must pass not call func() 
- arrow function also works 
### naming event handler - build in vs custom 
- html element has build-in 
  - onClick()
  - onSumbit
- custom element can have its own name
## event propagation 
- what: click child -> propagate(spread, bubble) to parent
- example below
  - when click button, it will trigger both onclick in button 
  - and then trigger div
```jsx
export default function Toolbar() {
  return (
    <div className="Toolbar" onClick={(e) => {
      alert('You clicked on the toolbar!');
    }}>
      <button onClick={() => alert('Playing!')}>
        Play Movie
      </button>
      <button onClick={() => alert('Uploading!')}>
        Upload Image
      </button>
    </div>
  );
}
```
### stop event propagation 
- add e.stopPropagation() in the child

```jsx
function Button({ onClick, children }) {
  return (
    <button onClick={e => {
      e.stopPropagation();
      onClick();
    }}>
      {children}
    </button>
  );
}

export default function Toolbar() {
  return (
    <div className="Toolbar" onClick={() => {
      alert('You clicked on the toolbar!');
    }}>
      <Button onClick={() => alert('Playing!')}>
        Play Movie
      </Button>
      <Button onClick={() => alert('Uploading!')}>
        Upload Image
      </Button>
    </div>
  );
}

```

### stop default
- different from propagation 
- eg, form 
  - once submit, it will reload 
  - use preventDefault() to stop
  - e.stopPropagation() stops the event handlers attached to the tags above from firing.
  - e.preventDefault() prevents the default browser behavior for the few events that have it.

```jsx
export default function Signup() {
  return (
    <form onSubmit={e => {
      e.preventDefault();
      alert('Submitting!');
    }}>
      <input />
      <button>Send</button>
    </form>
  );
}
```