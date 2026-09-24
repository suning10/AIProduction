
# split vs partition

## split 
- has no limit of # of splits 
  - can be limit by using maxsplit 

```markdown
raw.split(_FRONTMATTER_DELIMITER, 2)
```

## partition 
- used when need to check seperator
- always split into 3 

```markdown
key, separator, value = line.partition(":")

key: value
```