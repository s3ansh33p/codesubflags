import random
import asyncio
import time

#****************************************************************************
# Safe object
#****************************************************************************
class Safe:
    def __init__(self, num_digits=4):
        self.num_digits = num_digits
        self.start_time = None
        self.crack_time = None
        self.legal_combinations = []
        self._generate_combinations()
        self.combination = self._set_combination()
        self.cracked = asyncio.Condition()
        
        # The following are arrays used in the benchmark algorithms
        self.odds_array = self.generate_odds_array()
        self.sixes_array = self.generate_sixes_array()
        self.sixes_odds_array = self.legal_combinations
        self.team_array = []

    async def check_combination(self, attempt):
        async with self.cracked:
            if self.combination == attempt and self.start_time is not None:
                self.crack_time = time.time() - self.start_time
                self.cracked.notify_all()
                return True
        return False
            
    async def _change_combination(self, interval = 1):
        while True:
            await asyncio.sleep(interval)
            self.combination = random.choice(self.legal_combinations) # type: ignore
            
    async def run_safe(self, interval = 1, set_combination = None):
        self.crack_time = None
        self.start_time = time.time()

        if set_combination is not None and set_combination in self.legal_combinations:
            self.combination = set_combination

        task = asyncio.create_task(self._change_combination(interval))
        async with self.cracked:
            await self.cracked.wait()
        task.cancel()
        # End safe run

    def _generate_combinations(self):
        for combination in range(0, 10 ** self.num_digits - 1):
            if combination % 2 != 0 and '6' in str(combination):
                self.legal_combinations.append(combination)

    def _set_combination(self):
        return random.choice(self.legal_combinations)

    def reset(self):
        self.crack_time = None
        self.start_time = None
        self.cracked = asyncio.Condition()

    def reset_and_set_combination(self):
        self.reset()
        self.combination = self._set_combination()

    #**************************************************************************
    # Benchmark Algorithms
    # The following are benchmarked against the teams' algorithms
    #**************************************************************************

    # Level 1: Random guessing
    async def crack_combination_random(self):
        count = 0
        while True:
            combination = random.randint(0, 10 ** self.num_digits)
            cracked = await self.check_combination(combination)
            if cracked:
                print(f"RANDOM algorithm with {count} attempts" + f" took {self.crack_time:.8f} seconds")
                break
            count += 1

    # Level 2: Brute force
    async def crack_combination_loop(self):
        for combination in range(0, 10 ** self.num_digits):
            cracked = await self.check_combination(combination)
            if cracked:
                print(f"LOOP algorithm with {combination} attempts" + f" took {self.crack_time:.8f} seconds")
                break

    # Level 3: Brute force with odd numbers
    async def crack_combination_odds(self):
        # make a loop that goes through all possible combinations with odd numbers
        count = 0
        for combination in self.odds_array:
            count += 1
            cracked = await self.check_combination(combination)
            if cracked:
                print(f"ODDS algorithm with {count} attempts" + f" took {self.crack_time:.8f} seconds")
                break

    # Level 3: Brute force with 6 in one of the digits
    async def crack_combination_sixes(self):
        # make a loop that goes through all possible combinations with 6 in one of the digits
        count = 0
        for combination in self.sixes_array:
            count += 1
            cracked = await self.check_combination(combination)
            if cracked:
                print(f"SIXES algorithm with {count} attempts" + f" took {self.crack_time:.8f} seconds")
                break

    # Level 4: Brute force with 6 in one of the digits and odd numbers
    # Use the legal_combinations array
    async def crack_combination_sixes_odds(self):
        # make a loop that goes through all possible combinations with 6 in one of the digits and odd numbers
        count = 0
        for combination in self.legal_combinations:
            count += 1
            if count % 4 == 0:
                await asyncio.sleep(0)
            cracked = await self.check_combination(combination)
            if cracked:
                print(f"SIXES ODDS algorithm with {count} attempts" + f" took {self.crack_time:.8f} seconds")
                break

    #**************************************************************************
    # Benchmark Pre-Processing Arrays (Hashing)
    # The following are pregenerated arrays for the benchmark algorithms
    #**************************************************************************

    # Pregenerated array for sixes algorithm
    def generate_sixes_array(self):
        # Generate an array of combinations from 0 to 10 ** num_digits with 6 in one of the digits
        combinations = []
        for combination in range(0, 10 ** self.num_digits):
            if '6' in str(combination):
                combinations.append(combination)
        return combinations
    
    # Pregenerated array for odds algorithm
    def generate_odds_array(self):
        # Generate an array of combinations from 0 to 10 ** num_digits with odd numbers
        combinations = []
        for combination in range(0, 10 ** self.num_digits):
            if combination % 2 != 0:
                combinations.append(combination)
        return combinations
    
    # Pregenerated array for sixes odds algorithm
    def generate_sixes_odds_array(self):
        # Generate an array of combinations from 0 to 10 ** num_digits with odd numbers and 6 in one of the digits
        combinations = []
        for combination in range(0, 10 ** self.num_digits):
            if combination % 2 != 0 and '6' in str(combination):
                combinations.append(combination)
        return combinations
    
    #**************************************************************************
    # Control Centre
    # This is where the activity is processed and the algorithms are benchmarked
    #**************************************************************************
    async def start_cracking(self, team_algorithm, extra_parameter):
        self.num_digits = 4
        num_iterations = 10
        num_algorithms = 6

        crack_time_array = [0] * num_algorithms

        algorithms = [
            team_algorithm,
            self.crack_combination_random,
            self.crack_combination_loop,
            self.crack_combination_odds,
            self.crack_combination_sixes,
            self.crack_combination_sixes_odds
        ]

        for i in range(num_iterations):        
            print(" ====================== Iteration: " + str(i) + f" | KEY = {self.combination} ======================")
            
            for j in range(num_algorithms):
                safe_task = asyncio.create_task(self.run_safe(100))

                if j == 0:
                    cracker_task = asyncio.create_task(algorithms[j](self, extra_parameter))
                else:
                    cracker_task = asyncio.create_task(algorithms[j]())

                await asyncio.gather(safe_task, cracker_task)

                crack_time_array[j] += self.crack_time # type: ignore
        
                self.reset()
            # Print the fastest algorithm for each iteration
            print(f"Fastest algorithm for iteration {i}: {algorithms[crack_time_array.index(min(crack_time_array))].__name__}")
            self.reset_and_set_combination()

        average_time_array = [crack_time / num_iterations for crack_time in crack_time_array]

        # Summarise how well the team algorithm performed against the other algorithms
        print(" ====================== Cracking Algorithm Analysis ======================")
        for algorithm in algorithms:
            self.compare_speeds(average_time_array[0], average_time_array[algorithms.index(algorithm)], algorithm.__name__)

        # if the team algorithm is the fastest, print the safe code with a congrats message
        if average_time_array[0] == min(average_time_array):
            print("\nCongratulations! Your algorithm is the fastest!")
            print(f"The combination is {self.combination}. The contents of the safe is yours!")

    def compare_speeds(self, team_avg, algorithm_avg, algorithm_name):
        if(team_avg < algorithm_avg):
            print(f"Your algorithm beat the {algorithm_name} algorithm {algorithm_avg / team_avg :.2f} times faster")