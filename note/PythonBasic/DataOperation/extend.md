# Extend 

- when to use:
  - use when need to merge a list into another list 
    - **unpack and add each element**
  - Compare to append 
    - will result in [1,2,3,[3,4]]
  - compare to + 
    - does not modify original 


```python
nums = [1, 2, 3]

# append() → adds the item AS A SINGLE ELEMENT
nums.append([4, 5])
print(nums)  # [1, 2, 3, [4, 5]]  ← nested list!

# extend() → unpacks and adds each element
nums = [1, 2, 3]
nums.extend([4, 5])
print(nums)  # [1, 2, 3, 4, 5]  ← flat list!

# + operator → creates a NEW list (doesn't modify original)
nums = [1, 2, 3]
new_nums = nums + [4, 5]
print(nums)     # [1, 2, 3]       ← unchanged
print(new_nums) # [1, 2, 3, 4, 5] ← new list
```