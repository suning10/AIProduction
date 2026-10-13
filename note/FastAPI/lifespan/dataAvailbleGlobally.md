# State 

- why:
  - to share data globally 
    - db connection 
    - env setting
- how:
  - use app.state.anything

example
```python
    container = build_container(settings)
    app.state.container = container
```