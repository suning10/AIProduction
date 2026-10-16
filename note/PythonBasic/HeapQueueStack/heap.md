# use heap in python
- basic operation [basic operation](#basic-operation-)
  - push/offer/add
    - heapify
    - heappush(heap, item)
  - pop/poll
    - heappop(heap)
- default is min heap
  - heapify O(n)
- how to use max heap
  - push negative value 
- how to custom sort 
  - define new class
  - define __lt__
- how to address tie
  - add counter

## basic operation 
```python
import heapq

heap = []
heappush(heap, num)
heappop()

# NLargest
heappush(heap, num)
if len(heap) > k:
    heappop()

# one line
heapq.nlargest(k, nums)
# max heap -> use negative
```
## min-max-heap
```python
import heapq

max_heap = []
heapq.heappush(max_heap, -5)
heapq.heappush(max_heap, -1)
heapq.heappush(max_heap, -3)

print(-max_heap[0])              # peek → 5
print(-heapq.heappop(max_heap))  # poll → 5
```
## custom sort
```python
class HeapNode:
    def __init__(self, node):
        self.node = node
    def __lt__(self, other: HeapNode()):
        return self.node.val < other.node.val
```
## address tie
```python
counter = count()
heap = []

# (priority, tie-breaker, object)
heapq.heappush(heap, (1, next(counter), Task(1, "first")))
heapq.heappush(heap, (1, next(counter), Task(1, "second")))

_, _, task = heapq.heappop(heap)
print(task)   # Task(1, first) ← FIFO
```

