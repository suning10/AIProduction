useEffect 
- is a hook that runs after render
  - params
    - callback_func
    - [] when to trigger
      - [] during load
      - [user], only change when user changed 
- used when app first start
  - set up db connection
- use to get user session



```jsx
useEffect(() => {
    //return promise<User>
    me().then(setUser) // shortcut
    //this is similar to 
    me().then((response) => {setUser(response.user)})
})
```

### params
```tsx
  useEffect(() => {
    me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);
```