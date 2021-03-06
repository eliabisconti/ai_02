import configparser
import re
import time

from analyzers.chatAnalyzer import chatAnalyzer
from analyzers.gameAnalyzer import gameAnalyzer
from analyzers.playersAnalyzer import playersAnalyzer
from connection.chatConnection import ConnectToChat, ReceiveThread
from connection.serverConnection import connectToServer
from strategy.fuzzyStrategy import *
from strategy.lowLevelStrategy import lowLevelStrategy, lowLevelStrategyImpostor
from strategy.onMapFunctions import deterministicMap, whereItMoved, deterministicImpostorMap
from strategy.movement import *


class Karen:
    """
    Karen identify the AI-subsystem that is able to play an AmongAIs match
    """

    def __init__(self, name, strategyType):
        """
        Construct a new 'Karen' object.

        :param name: The name of the AI
        :return: returns nothing
        """
        # Identify the Karen as a Player
        gameStatus.game = Game(None)
        gameStatus.game.me = Player(name)

        gameStatus.game.me.movement = rb_movement(movement)
        self.strategyType = strategyType

        config = configparser.ConfigParser()
        config.read('config')

        self.host = config['connectionParam']['HOST']
        self.port = config['connectionParam']['PORT']
        self.delay = config['connectionParam']['DELAY']

        self.host_chat = config['chatParam']['HOST']
        self.port_chat = config['chatParam']['PORT']

        self.maxWeight = int(config['envParam']["MAXWEIGHT"])

        # Initialize the connection to the server and the chat system
        self.serverSocket = connectToServer(self.host, self.port, self.delay)

        self.ChatHOST = config['chatParam']['HOST']
        self.ChatPORT = config['chatParam']['PORT']

        self.chatSocket = ConnectToChat(self.ChatHOST, self.ChatPORT, gameStatus.game.me.name)
        t_r = ReceiveThread('Receive', self.chatSocket.net, gameStatus.game.me.name)
        t_r.start()

    def createGame(self, gameName, flags):
        time.sleep(0.5)

        """
        Create a new Game
        :param flags: T training, Q squared, W wide, 123 map dimension
        :param gameName: uniquely identifies the gameStatus.game.
        :return: True if created, False ow.
        """
        # A Karen can play one game at a time. Game encapsulate all the information about the map and other players
        if flags is not None:
            response = self.serverSocket.send("NEW " + gameName + " " + flags)
        else:
            response = self.serverSocket.send("NEW " + gameName)

        if response[0] == "OK Created":
            gameStatus.game.name = gameName
            print(gameStatus.game.me.name + " created a game room: " + gameName)
            return True
        else:
            print(response)
            return False

    def leaveGame(self, reason=None):
        """
        Let the AI leave a game room (works only if game started).
        :param reason: specify the reason why the AI leaved the gameStatus.game.
        :return: True if leaved, False ow.
        """
        # currently doesn't work [ERROR 404 Game not found]

        if gameStatus.game.name is None:
            print("You are not in any game at the moment.")
            return False
        if reason is None:
            response = self.serverSocket.send(gameStatus.game.name + "LEAVE")
        else:
            response = self.serverSocket.send(gameStatus.game.name + "LEAVE" + " " + reason)
        if response[0] == "OK":
            print(gameStatus.game.me.name + " leaved the game " + gameStatus.game.name)
            gameStatus.game.name = None
            return True
        else:
            print(gameStatus.game.me.name + ": " + response[0])
            return False

    def joinGame(self, gameName, nature, role, userInfo=None):
        time.sleep(0.6)
        """
        Let the AI join a game
        :param gameName: specify which game the AI want to join.
        :param nature: specify that the player is the AI.
        :param role: specify the role of the AI. (normal player, impostor and so on)
        :param userInfo: extra user info.
        :return: True if joined, False ow.
        """
        # <game> JOIN <player-name> <nature> <role> <user-info>
        gameStatus.game.name = gameName
        gameStatus.game.me.nature = nature
        gameStatus.game.me.role = role
        gameStatus.game.me.userInfo = userInfo
        cmd = gameName + " JOIN " + gameStatus.game.me.name + " " + nature + " " + role
        if userInfo is not None:
            cmd += " " + userInfo

        response = self.serverSocket.send(cmd)

        if response[0].startswith("OK"):
            row = re.split(' |=', response[0])
            gameStatus.game.me.team = row[2]
            gameStatus.game.me.loyalty = row[4]

            self.chatSocket.connectToChannel(gameStatus.game.name)
            return True

        else:
            gameStatus.game.name = None
            print(gameStatus.game.me.name + ": " + response[0])
            return False

    def startGame(self):
        """
        Send Start command to the server. Only the AI who create the room can start the gameStatus.game.
        :return: True if the game started, False ow.
        """
        self.lookStatus()

        response = self.serverSocket.send(gameStatus.game.name + " START")

        if response[0] == 'OK Game started':
            print(gameStatus.game.name + " started.")

            return self.waitToStart()
        else:
            print(gameStatus.game.name + " " + response[0])
            return False

    def lookStatus(self):
        """
        Retrieve information about the game status and of all the player (allies and enemies) in that room.
        :return: True if information updated, False ow.
        """
        response = self.serverSocket.send(gameStatus.game.name + " STATUS")

        if response[0] == 'OK LONG':
            for s in range(0, len(response)):
                # Parse information about the Game
                if response[s].startswith("GA:"):
                    row = re.split(' |=', response[s])
                    gameStatus.game.name = row[2]
                    gameStatus.game.state = row[4]
                    gameStatus.game.size = row[6]

                # Parse information about Karen
                if response[s].startswith("ME:"):
                    row = re.split(' |=', response[s])
                    gameStatus.game.me.symbol = row[2]
                    gameStatus.game.me.name = row[4]
                    gameStatus.game.me.team = row[6]
                    gameStatus.game.me.loyalty = row[8]
                    gameStatus.game.me.energy = row[10]
                    gameStatus.game.me.score = row[12]

                # Parse information about other players (allies or enemies)
                elif response[s].startswith("PL:"):
                    row = re.split(' |=', response[s])

                    # Karen is also present in the PLAYER list
                    if row[2] == gameStatus.game.me.symbol:

                        # reset map cell
                        if gameStatus.game.serverMap is not None:
                            gameStatus.game.serverMap[gameStatus.game.me.y][gameStatus.game.me.x] = "."

                        gameStatus.game.me.x = int(row[8])
                        gameStatus.game.me.y = int(row[10])
                        gameStatus.game.me.state = row[12]

                        # refresh my position on the map
                        if gameStatus.game.serverMap is not None:
                            gameStatus.game.serverMap[gameStatus.game.me.y][
                                gameStatus.game.me.x] = gameStatus.game.me.symbol

                    # Not Karen, update information of other players

                    else:
                        if gameStatus.game.allies.get(row[2]) is None and gameStatus.game.enemies.get(row[2]) is None:
                            pl = Player(row[4])
                            pl.symbol = row[2]
                            pl.team = row[6]
                            pl.x = int(row[8])
                            pl.y = int(row[10])
                            pl.state = row[12]
                            if pl.team == gameStatus.game.me.team:
                                gameStatus.game.allies[pl.symbol] = pl
                            else:
                                gameStatus.game.enemies[pl.symbol] = pl

                        elif gameStatus.game.allies.get(row[2]) is not None:

                            # reset map cell
                            if gameStatus.game.serverMap is not None:
                                gameStatus.game.serverMap[gameStatus.game.allies.get(row[2]).y][
                                    gameStatus.game.allies.get(row[2]).x] = "."
                            gameStatus.game.allies.get(row[2]).x = int(row[8])
                            gameStatus.game.allies.get(row[2]).y = int(row[10])
                            gameStatus.game.allies.get(row[2]).state = row[12]

                            # refresh ally position on the map
                            if gameStatus.game.serverMap is not None:
                                gameStatus.game.serverMap[gameStatus.game.allies.get(row[2]).y][
                                    gameStatus.game.allies.get(row[2]).x] = gameStatus.game.allies.get(row[2]).symbol

                        elif gameStatus.game.enemies.get(row[2]) is not None:

                            # reset map cell
                            if gameStatus.game.serverMap is not None:
                                gameStatus.game.serverMap[gameStatus.game.enemies.get(row[2]).y][
                                    gameStatus.game.enemies.get(row[2]).x] = "."
                                # adding the action sequence made by an enemy.
                                sequence = whereItMoved(gameStatus.game.enemies.get(row[2]).x, gameStatus.game.enemies.get(row[2]).y, int(row[8]), int(row[10]))
                                """
                                print(str(row[2]) + " prima sequenza: " + str(
                                    gameStatus.game.enemies.get(row[2]).actionList))
                                print(str(row[2]) + " Sequenza " + str(sequence))
                                """
                                gameStatus.game.enemies.get(row[2]).actionList.extend(sequence)

                            gameStatus.game.enemies.get(row[2]).x = int(row[8])
                            gameStatus.game.enemies.get(row[2]).y = int(row[10])
                            gameStatus.game.enemies.get(row[2]).state = row[12]

                            # refresh enemy position on the map
                            if gameStatus.game.serverMap is not None:
                                gameStatus.game.serverMap[gameStatus.game.enemies.get(row[2]).y][
                                    gameStatus.game.enemies.get(row[2]).x] = gameStatus.game.enemies.get(row[2]).symbol

            '''
            if gameStatus.game.serverMap is not None:
                for row in gameStatus.game.serverMap:
                    print(row)
            '''

            return True

        else:
            return False

    def lookAtMap(self, firstTime):

        def split(word):
            return [char for char in word]

        """
        Let the AI to look at the map (works only if the game started).
        This function update all the information about the players in the 'Game' structure.
        :param firstTime: True if this is the first time the function is called. Used to retrieve FLAGS position.
        :return: The map if available, None ow.
        """
        response = self.serverSocket.send(gameStatus.game.name + " LOOK")

        if response[0] == 'OK LONG':
            response.pop(0)
            response.pop(len(response) - 1)
            actualMap = []

            for i in range(0, len(response)):

                splitted = split(response[i])
                for j in range(0, len(splitted)):
                    # For each symbol in the map, check if it identifies a player. If so, update its position information
                    if gameStatus.game.allies.get(splitted[j]) is not None:
                        gameStatus.game.allies.get(splitted[j]).x = j
                        gameStatus.game.allies.get(splitted[j]).y = i

                    elif gameStatus.game.enemies.get(splitted[j]) is not None:

                        # adding the action sequence made by an enemy.
                        if firstTime is False:
                            sequence = whereItMoved(gameStatus.game.enemies.get(splitted[j]).x, gameStatus.game.enemies.get(splitted[j]).y, j, i)

                            gameStatus.game.enemies.get(splitted[j]).actionList.extend(sequence)



                        gameStatus.game.enemies.get(splitted[j]).x = j
                        gameStatus.game.enemies.get(splitted[j]).y = i
                    elif gameStatus.game.me.symbol == splitted[j]:
                        gameStatus.game.me.x = j
                        gameStatus.game.me.y = i

                    # Used only the first time that Karen looks at the map. Find FLAGS position
                    if firstTime is True:

                        if splitted[j] == "x" and gameStatus.game.me.symbol.isupper():
                            gameStatus.game.wantedFlagName = "x"
                            gameStatus.game.wantedFlagX = j
                            gameStatus.game.wantedFlagY = i
                        elif splitted[j] == "x" and gameStatus.game.me.symbol.islower():
                            gameStatus.game.toBeDefendedFlagName = "x"
                            gameStatus.game.toBeDefendedFlagX = j
                            gameStatus.game.toBeDefendedFlagY = i
                        elif splitted[j] == "X" and gameStatus.game.me.symbol.islower():
                            gameStatus.game.wantedFlagName = "X"
                            gameStatus.game.wantedFlagX = j
                            gameStatus.game.wantedFlagY = i
                        elif splitted[j] == "X" and gameStatus.game.me.symbol.isupper():
                            gameStatus.game.toBeDefendedFlagName = "X"
                            gameStatus.game.toBeDefendedFlagX = j
                            gameStatus.game.toBeDefendedFlagY = i

                actualMap.append(splitted)

                if firstTime is True:
                    gameStatus.game.mapWidth = len(actualMap[0])
                    gameStatus.game.mapHeight = len(actualMap)

            return actualMap

        else:
            print("Map not retrieved.")
            return None

    def nop(self):
        """
        Send a NOP command. (keep alive control)
        :return:
        """
        return self.serverSocket.send(gameStatus.game.name + " NOP")

    def move(self, direction):
        """
         Basic function that send the "MOOVE" command to the server
         :param direction: define where the AI wants to move.
         :return: 'OK moved', 'Ok blocked' or 'ERROR'
         """
        if direction is None:
            return False
        response = self.serverSocket.send(gameStatus.game.name + " MOVE " + direction)
        if response[0] == "OK moved":
            # print('Ok moved')
            return True
        return False

    def shoot(self, direction):
        """
        Basic function that send the "SHOOT" command to the server
        :param direction: define where the AI wants to shoot.
        :return: 'OK x' where x is the position where the bullet landed
        """
        return self.serverSocket.send(gameStatus.game.name + " SHOOT " + direction)

    def accuse(self, playerName):
        """
         Basic function that send the "ACCUSE" command to the server
         :param: 'playerName', name of the player that I want to vote
         :return: 'OK noted', or 'ERROR'
         """
        response = self.serverSocket.send(gameStatus.game.name + " ACCUSE " + playerName)
        if response[0] == "OK":
            return True
        return False

    def judge(self, playerName, playerNature):
        """
         Basic function that send the "JUDGE" command to the server
         :param: 'playerName', name of the player that I want to vote
         :param: 'playerNature', nature of the player
         :return: 'OK noted',  or 'ERROR'
         """
        response = self.serverSocket.send(gameStatus.game.name + " JUDGE " + playerName + ' ' + playerNature)
        # print('Risposta di judge: ' + response[0])
        if response[0] == "OK":
            return True
        return False

    def waitToStart(self):
        """
        Wait until the game start.
        :return: start strategy if started. False on ERROR.
        """
        self.lookStatus()

        chat_analyzer = chatAnalyzer("chatAnalyzer")
        chat_analyzer.start()

        while gameStatus.game.state == "LOBBY":
            self.lookStatus()

        if gameStatus.game.state == "ACTIVE":
            self.strategy(self.strategyType)
        else:
            print("Error. Game status from LOBBY to " + str(gameStatus.game.state) + gameStatus.game.me.name)
            return False
        return True

    def strategy(self, strategyType):
        """
        Strategies Dispatcher
        :param strategyType: the type of the strategy. Defined in Karen's init
        :return: -
        """

        gameStatus.game.serverMap = self.lookAtMap(True)
        gameStatus.game.weightedMap = deterministicMap(self.maxWeight)

        players_analyzer = playersAnalyzer("playersAnalyzer")
        players_analyzer.start()

        game_analyzer = gameAnalyzer("gameAnalyzer", self.maxWeight)
        game_analyzer.start()

        if strategyType == "lowLevelStrategy":
            self.llStrategy()

        if strategyType == "fuzzyStrategy":
            if( gameStatus.game.me.team == gameStatus.game.me.loyalty):
                self.fStrategy()
            else:
                self.fStrategyImpostor()

        else:
            print("Hai sbagliato nome della strategy. Riprova controllando i param di Karen.")
            return False

    def llStrategy(self):
        """
        Call the lowLevelStrategy. Run to the flag with only basic forecasting decisions *PROTO1*
        :return: True at the end of the game
        """

        while gameStatus.game.state != 'FINISHED' and gameStatus.game.me.state != "KILLED":

            nextActions = lowLevelStrategy(self.maxWeight, gameStatus.game.wantedFlagX, gameStatus.game.wantedFlagY)
            # self.chatSocket.sendInChat(gameStatus.game.name, "You are a bitch!!!")
            for (action, direction) in nextActions:
                if action == "move":
                    self.move(direction)
                if action == "shoot":
                    self.shoot(direction)

            # AGGIORNAMENTO
            gameStatus.game.serverMap = self.lookAtMap(False)
            gameStatus.game.weightedMap = deterministicMap(self.maxWeight)

            # self.lookStatus()

        if gameStatus.game.state != "FINISHED":
            print(gameStatus.game.me.name + " è morto.")

        while gameStatus.game.state == "ACTIVE":
            self.lookStatus()

        return True

    def fStrategy(self):

        """
        Call the fuzzyStrategy. Uses fuzzy rule to take the best decision.
        """

        while gameStatus.game.state != 'FINISHED' and gameStatus.game.me.state != "KILLED":
            doIneedToCheckEnergy = False


            endx, endy = FuzzyControlSystem(self.maxWeight)
            # Avoid useless LOOK if I can't die moving

            if endx is None or endy is None or endx < 0 or endy < 0 or endx > gameStatus.game.mapWidth or endy > gameStatus.game.mapHeight:
                endx = gameStatus.game.wantedFlagX
                endy = gameStatus.game.wantedFlagY

            nearestEnemyDistance = gameStatus.game.nearestEnemyLinearDistance[0]
            if nearestEnemyDistance is not None and int(nearestEnemyDistance // 2) > 2:

                numberOfSafeMovement = int(nearestEnemyDistance//2)
                '''
                if gameStatus.game.me.symbol == "A":
                    print(str(gameStatus.game.me.name) + " nearest enemy distance: " + str(numberOfSafeMovement*2) + " " + str(gameStatus.game.nearestEnemyLinearDistance[1]) + " " + str(gameStatus.game.nearestEnemyLinearDistance[2]))

                    for k in gameStatus.game.serverMap:
                        print (k)
                    for k in gameStatus.game.weightedMap:
                        print(k)
                '''

                for i in range(1, numberOfSafeMovement):

                    # se c'è un emergency meeting e sto safe, posso accusare
                    if gameStatus.game.emergencyMeeting == 1:
                        playerToAccuse = [None, 0]
                        for k in gameStatus.game.allies.keys():
                            if gameStatus.game.allies.get(k).sdScore > playerToAccuse[1]:
                                playerToAccuse = [gameStatus.game.allies.get(k).name, gameStatus.game.allies.get(k).sdScore]
                        if playerToAccuse[1] > 0.5:
                            self.accuse(playerToAccuse[0])
                        gameStatus.game.emergencyMeeting = 0


                    # se c'è qualcosa da votare vota uno else muoviti
                    elif len(gameStatus.game.judgeList) > 0:
                        obj = gameStatus.game.judgeList.pop()
                        obj_name = obj[0]
                        obj_nature = obj[1]
                        # print(str(gameStatus.game.me.name) + 'giudica : ' + obj_name + ' ' + obj_nature + '\n')
                        self.judge(obj_name, obj_nature)

                    else:
                        try:
                            direction, coordinates = gameStatus.game.me.movement.move(gameStatus.game.weightedMap,
                                                                                      gameStatus.game.me, endx, endy)
                            if direction is not None:
                                if self.move(direction):
                                    gameStatus.game.me.x = coordinates[0]
                                    gameStatus.game.me.y = coordinates[1]
                        except():
                            print("Exception generated by movement.move in karen.")
                        if gameStatus.game.me.x == endx and gameStatus.game.me.y == endy:
                            break

            else:

                # print("LOW LEVEL")

                nextActions = lowLevelStrategy(self.maxWeight, endx, endy)

                for (action, direction) in nextActions:
                    if action == "move":
                        self.move(direction)
                    if action == "shoot":
                        self.shoot(direction)
                        doIneedToCheckEnergy = True

            # AGGIORNAMENTO
            if doIneedToCheckEnergy is True:
                self.lookStatus()
            else:
                gameStatus.game.serverMap = self.lookAtMap(False)

            gameStatus.game.weightedMap = deterministicMap(self.maxWeight)


        if gameStatus.game.state != "FINISHED":
            print(gameStatus.game.me.name + " è morto.")

        while gameStatus.game.state == "ACTIVE":
            self.lookStatus()
            # se sono morto e il gioco è attivo posso ancora votare
            if len(gameStatus.game.judgeList) > 0:
                pl = gameStatus.game.judgeList.pop()
                pl_name = pl[0]
                pl_nature = pl[1]
                self.judge(pl_name, pl_nature)

        return True

    def fStrategyImpostor(self):
        """
        Call the fuzzyStrategy related to the impostor. Uses fuzzy rule to take the best decision.
        """
        gameStatus.game.weightedImpostorMap = deterministicImpostorMap(self.maxWeight)

        while gameStatus.game.state != 'FINISHED' and gameStatus.game.me.state != "KILLED":
            doIneedToCheckEnergy = False

            endx, endy = FuzzyControlSystemImpostor(self.maxWeight)
            # Avoid useless LOOK if I can't die moving

            if endx is None or endy is None or endx < 0 or endy < 0 or endx > gameStatus.game.mapWidth or endy > gameStatus.game.mapHeight:
                if gameStatus.game.wantedFlagEuclideanDistance > gameStatus.game.wantedFlagMaxEuclideanDistance / 4:
                    endx = gameStatus.game.toBeDefendedFlagX
                    endy = gameStatus.game.toBeDefendedFlagY
                else:
                    endx = gameStatus.game.wantedFlagX
                    endy = gameStatus.game.wantedFlagY

            nearestEnemyDistance = gameStatus.game.nearestEnemyLinearDistance[0]
            if int(nearestEnemyDistance // 2) > 2:

                numberOfSafeMovement = int(nearestEnemyDistance // 2)

                '''
                if gameStatus.game.me.symbol == "A":
                    print(str(gameStatus.game.me.name) + " nearest enemy distance: " + str(numberOfSafeMovement*2) + " " + str(gameStatus.game.nearestEnemyLinearDistance[1]) + " " + str(gameStatus.game.nearestEnemyLinearDistance[2]))

                    for k in gameStatus.game.serverMap:
                        print (k)
                    for k in gameStatus.game.weightedMap:
                        print(k)
                '''

                for i in range(1, numberOfSafeMovement):

                    # se c'è un emergency meeting e sto safe, posso accusare
                    if gameStatus.game.emergencyMeeting == 1:
                        playerToAccuse = [None, 0]
                        for k in gameStatus.game.allies.keys():
                            if gameStatus.game.allies.get(k).sdScore > playerToAccuse[1]:
                                playerToAccuse = [gameStatus.game.allies.get(k).name,
                                                  gameStatus.game.allies.get(k).sdScore]
                        if playerToAccuse[1] > 0.5:
                            self.accuse(playerToAccuse[0])
                        gameStatus.game.emergencyMeeting = 0

                    # se c'è qualcosa da votare vota uno else muoviti
                    elif len(gameStatus.game.judgeList) > 0:
                        pl = gameStatus.game.judgeList.pop()
                        pl_name = pl[0]
                        pl_nature = pl[1]
                        self.judge(pl_name, pl_nature)

                    else:
                        try:
                            direction, coordinates = gameStatus.game.me.movement.move(gameStatus.game.weightedMap,
                                                                                      gameStatus.game.me, endx, endy)
                            if direction is not None:
                                if self.move(direction):
                                    gameStatus.game.me.x = coordinates[0]
                                    gameStatus.game.me.y = coordinates[1]
                        except():
                            print("Exception generated by movement.move in karen.")
                        if gameStatus.game.me.x == endx and gameStatus.game.me.y == endy:
                            break

            else:

                # print("LOW LEVEL")

                nextActions = lowLevelStrategy(self.maxWeight, endx, endy)

                for (action, direction) in nextActions:
                    if action == "move":
                        self.move(direction)
                    if action == "shoot":
                        self.shoot(direction)
                        doIneedToCheckEnergy = True

            # AGGIORNAMENTO
            if doIneedToCheckEnergy is True:
                self.lookStatus()
            else:
                gameStatus.game.serverMap = self.lookAtMap(False)

            gameStatus.game.weightedMap = deterministicMap(self.maxWeight)
            gameStatus.game.weightedImpostorMap = deterministicImpostorMap(self.maxWeight)


        if gameStatus.game.state != "FINISHED":
            print(gameStatus.game.me.name + " è morto.")

        while gameStatus.game.state == "ACTIVE":
            self.lookStatus()
            if len(gameStatus.game.judgeList) > 0:
                pl = gameStatus.game.judgeList.pop()
                pl_name = pl[0]
                pl_nature = pl[1]
                self.judge(pl_name, pl_nature)

        return True
