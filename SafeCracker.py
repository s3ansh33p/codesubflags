import Safe as Safe
import asyncio
import random

#********************************************************************************************
# Welcome to the Safe Cracker challenge!
#
# GOAL: 
# Write an algorithm that cracks the safe in the shortest amount of time.
#
# RULES:
# 1. You can only use the check_combination method to check if a combination is correct.
# 2. No peaking at the combination! (You can't use the combination variable)
# 3. Clue: You get one extra parameter which can be processed prior to 
#    starting the cracking process.
#********************************************************************************************

# Use this snipped to check a combination:
    # cracked = await safe.check_combination(combination)
    # if cracked:
    #     print(f"Cracked the safe using YOUR TEAM'S algorithm with {count} attempts" + f" The combination is {combination} and it took {safe.crack_time:.8f} seconds")
    #     break

async def crack_the_safe(safe, array):
    # Implement your safe cracking algorithm here!
    count = 0

# Main function
async def main():
    safe = Safe.Safe(4)
    
    await safe.start_cracking(crack_the_safe, array) # type: ignore

if __name__ == '__main__':
    asyncio.run(main())