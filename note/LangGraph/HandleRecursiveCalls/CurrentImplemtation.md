# current implementation of detect infinite tool calls

 - detect duplicate call
   - get signature 
   - get toolcallhistory
   - compare signature 
   - if tool_name is the same 
     - compare args similarity using difflib (utils/graph)
       - only compare # of words in same 

- detect cycle (utils/graph)
  - using sliding window 
    - pattern [:period]
    - window period * min_repeat 
    - tail[:-window]
    - maintain a sliding window of len(period)
      - check each pattern == period 
      

