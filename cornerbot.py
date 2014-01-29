# Your AI for CTF must inherit from the base Commander class.  See how this is
# implemented by looking at the commander.py in the ./api/ folder.
from api import Commander

# The commander can send 'Commands' to individual bots.  These are listed and
# documented in commands.py from the ./api/ folder also.
from api import commands

# The maps for CTF are layed out along the X and Z axis in space, but can be
# effectively be considered 2D.
from api import Vector2

from collections import deque
import math
import logging
import sys

class CornerBot(Commander):
   """
   Does some awesome things.
   """

   def initialize(self):
      loghandler = logging.StreamHandler(sys.stdout)
      loghandler.setLevel(logging.DEBUG)
      self.log.addHandler(loghandler)

      self.myAttackers = set()
      self.myDefenders = set()
      self.attackers = {}
      self.facingAttackers = {}
      self.maxDefenders = 4
      self.verbose = False

      self.numEnemies = len(self.game.bots_alive)
      self.timeToRespawn = self.game.match.timeToNextRespawn 
      self.parsedCombatEvents = set()
      self.lastCommand = {}
      self.lastTarget = {}

      # Calculate flag positions and store the middle.
      ours = self.game.team.flag.position
      theirs = self.game.enemyTeam.flag.position
      self.middle = Vector2(self.level.width/2,self.level.height/2)

      # Now figure out the flaking directions, assumed perpendicular.
      #d = (ours - theirs)
      d = self.game.team.flagScoreLocation - theirs
      self.left = Vector2(-d.y, d.x).normalized()
      self.right = Vector2(d.y, -d.x).normalized()
      self.front = Vector2(-d.x, -d.y).normalized()
      self.back = Vector2(d.x, d.y).normalized()
      self.frontleft = (self.front+self.left).normalized()
      self.frontright = (self.front+self.right).normalized()

      awayFromEnemyFlag = self.middle - theirs
      self.attackDirections = [self.rotateVector(awayFromEnemyFlag,theta) for theta in [math.pi*1/8,math.pi*-1/8,math.pi*2/8,math.pi*-2/8,math.pi*3/8,math.pi*-3/8]]
      self.attackPositions = [theirs + x.normalized() * self.level.firingDistance*1.3 for x in self.attackDirections]

      self.findDefendPosition()



      
   def tick(self):    
      self.parseCombatEvents()
      if(self.timeToRespawn < self.game.match.timeToNextRespawn ):
         self.numEnemies = len(self.game.bots_alive)
      self.timeToRespawn = self.game.match.timeToNextRespawn

      for bot in self.game.team.members:
         if bot.health <= 0:
            self.myAttackers.discard(bot)
            self.myDefenders.discard(bot)
            self.facingAttackers.pop(bot, None)

      for bot in self.game.bots_available:
         if bot in self.myDefenders or ((len(self.myDefenders)<self.maxDefenders) and len(self.myDefenders) <= self.numEnemies):
            distanceToHomeFlag = Vector2.distance(bot.position,self.game.team.flagSpawnLocation)
            distanceToEnemyFlag = Vector2.distance(bot.position, self.game.enemyTeam.flagSpawnLocation)
            if distanceToEnemyFlag > distanceToHomeFlag or len(self.myAttackers) >= 3:
               self.goDefend(bot)
            else:
               self.goAttack(bot)
         else:
            self.goAttack(bot)

      for bot in self.game.bots_alive:
         if bot.state == bot.STATE_SHOOTING:
            continue
         if bot.state == bot.STATE_TAKINGORDERS:
            continue
         if bot.state == bot.STATE_DEFENDING and bot.flag :
            self.goAttack(bot)
            continue
         if (bot in self.myDefenders):
            self.defenseTick(bot)
         if (bot in self.myAttackers):
            self.attackTick(bot)

   def defenseTick(self, bot):
      if not (Vector2.distance(bot.position,self.game.team.flagSpawnLocation) > self.level.firingDistance and self.attackCloseEnemy(bot)):
         if len(self.closeVisibleLivingEnemies(bot)) > 1:
            for defender in self.myDefenders:
               if not self.visibleLivingEnemies(defender) and defender.state == defender.STATE_DEFENDING and self.lastCommand[defender] != 'doubling up':
                  dir = [bot.facingDirection,defender.facingDirection]
                  self.issueAndStore(commands.Defend, defender, dir, description = 'doubling up')
         if len(self.myAttackers) < 2 and len(self.myDefenders) > self.numEnemies and not bot.seenBy:
            self.goAttack(bot)

   def attackTick(self, bot):
      self.attackCloseEnemy(bot)
      if bot.state == bot.STATE_ATTACKING and self.closestEnemy(bot) is None:
         if self.lastCommand[bot] != "attack enemy flag":
            self.goAttack(bot)
      if bot.state == bot.STATE_DEFENDING and self.game.enemyTeam.flag.carrier is None:
         self.goAttack(bot)
      enemyFlag = self.game.enemyTeam.flag.position
      if self.lastCommand[bot] == "charge to attack position" and bot.position.distance(self.lastTarget[bot]) > bot.position.distance(enemyFlag):
         self.issueAndStore(commands.Charge, bot, enemyFlag, description = 'charge enemy flag')
      if bot.flag and (bot.state == bot.STATE_CHARGING or bot.state == bot.STATE_ATTACKING) and not self.visibleLivingEnemies(bot):
         self.goAttack(bot)


   def goAttack(self, bot):
      self.myAttackers.add(bot)
      self.myDefenders.discard(bot)
      self.resetDefenders()
      distanceToHomeFlag = Vector2.distance(bot.position,self.game.team.flagSpawnLocation)
      distanceToEnemyFlag = Vector2.distance(bot.position, self.game.enemyTeam.flagSpawnLocation)
      enemyFlagSpawn = self.game.enemyTeam.flagSpawnLocation
      enemyFlag = self.game.enemyTeam.flag.position
      if not self.attackCloseEnemy(bot):
         if bot.flag:
            # Tell the flag carrier to run home!
            target = self.game.team.flagScoreLocation
            self.issueAndStore(commands.Move, bot, target, description = 'running home')
         else:
            if self.game.enemyTeam.flag.carrier == None:
               if distanceToEnemyFlag > self.level.firingDistance*1.6:
                  pos1 = self.attackPositions[0]
                  self.attackPositions = self.attackPositions[1:] + [self.attackPositions[0]]
                  pos2 = self.attackPositions[0]
                  self.attackPositions = self.attackPositions[1:] + [self.attackPositions[0]]
                  position = min([pos1,pos2], key=lambda x:Vector2.distance(bot.position,x))
                  position = self.level.findNearestFreePosition(position)
                  self.issueAndStore(commands.Charge, bot, position, description = 'charge to attack position')
               else:
                  self.issueAndStore(commands.Charge, bot, enemyFlag,enemyFlag, description = 'Charge enemy flag')
            else:
               if distanceToEnemyFlag <= self.level.characterRadius:
                  faceSpawn1 = self.game.enemyTeam.botSpawnArea[0]-bot.position
                  faceSpawn2 = self.game.enemyTeam.botSpawnArea[1]-bot.position
                  faceMiddle = Vector2(self.level.width/2,self.level.height/2)-bot.position
                  faceDirs = [faceSpawn1,faceMiddle]
                  self.issueAndStore(commands.Defend, bot, faceDirs, description = 'defend enemy flag')
               else:
                  self.issueAndStore(commands.Charge, bot, enemyFlagSpawn, description = 'charge to enemy flagSpawn')


   def goDefend(self, bot):
      # defend the flag!
      self.facingAttackers.pop(bot, None)
      self.myDefenders.add(bot)
      self.myAttackers.discard(bot)
      if bot.flag:
         #bring it hooome
         scoreLocation = self.game.team.flagScoreLocation
         self.issueAndStore(commands.Charge, bot, scoreLocation, description = 'bring flag home')
      else:
         if (self.defendPosition - bot.position).length() > 1:
            self.issueAndStore(commands.Charge, bot, self.defendPosition, description = 'move to wall')
         else:
            if not self.resetDefenders():
               dir = self.defendDirections[0]
               self.defendDirections.append(self.defendDirections.pop(0))
               self.issueAndStore(commands.Defend, bot, dir, description = 'defend flag')
            
      
   def closestDefender(self, enemy):
      closest = min(self.myDefenders, key=lambda x:Vector2.distance(x.position,enemy.position))
      return closest
      
   def closestEnemy(self, bot):
      closest = None
      visibleLivingEnemies = self.visibleLivingEnemies(bot)
      if visibleLivingEnemies:
         closest = min(visibleLivingEnemies, key=lambda x:Vector2.distance(bot.position,x.position))
      return closest
      
   def visibleLivingEnemies(self, bot):
      livingEnemies = []
      for enemy in bot.visibleEnemies:
         if enemy.health > 0:
            livingEnemies.append(enemy)
      return livingEnemies

   def closeVisibleLivingEnemies(self, bot):
      closeLivingEnemies = []
      for enemy in bot.visibleEnemies:
         if enemy.health > 0 and bot.position.distance(enemy.position) < self.level.firingDistance*1.5:
            closeLivingEnemies.append(enemy)
      return closeLivingEnemies
   
   def enemyInRange(self, bot):
      for enemy in self.visibleLivingEnemies(bot):
         enemyDistance = Vector2.distance(bot.position, enemy.position)
         if(enemyDistance <= self.level.firingDistance):
            return True
      return False

   def enemyJustOutsideRange(self, bot):
      closestEnemy = self.closestEnemy(bot)
      if not closestEnemy == None:
         if Vector2.distance(bot.position, closestEnemy.position) < self.level.firingDistance + self.level.firingDistance/4:
            return closestEnemy
      return None
         
   def parseCombatEvents(self):
      for event in self.game.match.combatEvents:
         if not event.time in self.parsedCombatEvents:
            if event.type == event.TYPE_KILLED:
               self.parsedCombatEvents.add(event.time)
               self.myAttackers.discard(event.subject)
               if event.subject.name in self.myDefenders:
                  self.myDefenders.discard(event.subject)
                  self.resetDefenders()
               if event.subject.name in [x.name for x in self.game.enemyTeam.members]:
                  self.numEnemies -= 1
                  self.resetDefenders()
               #self.log.info( "Enemies:" + str(self.numEnemies) + " Defenders:" + str(len(self.myDefenders)) + " Attackers:" + str(len(self.myAttackers)))

   def rotateVector(self, v, theta):
      newx = math.cos(theta)*v.x - math.sin(theta)*v.y
      newy = math.sin(theta)*v.x + math.cos(theta)*v.y
      return Vector2(newx, newy)

   def getPositionInFrontOf(self, bot):
      return self.level.findNearestFreePosition(bot.position + 3*bot.facingDirection)
     
   def angle(self, vect1, vect2):
      if type(vect2) == type((1,2)):
         vect2 = vect2[0]
      dot = vect1.dotProduct(vect2)
      return math.acos(dot/(Vector2.length(vect1) + Vector2.length(vect2)))

   def maximizeLineOfSite(self, vect1, vect2):
      if type(vect2) == type((1,2)):
         vect2 = vect2[0]
      dot = vect1.dotProduct(vect2)
      return math.acos(dot/(Vector2.length(vect1) + Vector2.length(vect2)))

   def isInsideSpawn(self, bot):
      min = self.game.enemyTeam.botSpawnArea[0]
      max = self.game.enemyTeam.botSpawnArea[1]
      if bot.position.x >= min.x and bot.position.x <= max.x and bot.position.y >= min.y and bot.position.y <= max.y:
         return True
      return False

   def resetDefenders(self):
      if self.cheating:
         return False
      if all(Vector2.distance(self.closestEnemy(x).position,x.position) >self.level.firingDistance*1.6 for x in self.myDefenders if self.closestEnemy(x) is not None):
         self.resetDefendDirections()
         for defender in self.myDefenders:
            if (self.defendPosition - defender.position).length() <= 2:
               dir = self.defendDirections[0]
               self.defendDirections.append(self.defendDirections.pop(0))
               self.issueAndStore(commands.Defend, defender, dir, description = 'defend flag')
         return True
      return False

   def attackCloseEnemy(self, bot):
      closestEnemy = self.closestEnemy(bot)
      if closestEnemy is not None and not self.isInsideSpawn(closestEnemy):
         if bot.flag:
            enemyDistanceFromHome = Vector2.distance(closestEnemy.position,self.game.team.flagScoreLocation)
            botDistanceFromHome = Vector2.distance(bot.position,self.game.team.flagScoreLocation)
            if closestEnemy in bot.seenBy or enemyDistanceFromHome > botDistanceFromHome:
               return False
         enemyDistance = Vector2.distance(closestEnemy.position,bot.position)
         if closestEnemy.state == closestEnemy.STATE_DEFENDING and closestEnemy in bot.seenBy:
            if enemyDistance < self.level.firingDistance*1.4 and enemyDistance > self.level.firingDistance:
               enemyDir = (closestEnemy.position - bot.position).normalized()
               perpendicular = enemyDir.perpendicular().normalized()
               flank = bot.position + enemyDir*2 + perpendicular*6*self.isLeftOf(bot,closestEnemy)
               flank = self.level.findNearestFreePosition(flank)
               if flank is not None:
                  if self.lastCommand[bot] != 'attack defender' or Vector2.distance(bot.position,self.lastTarget[bot])<self.level.characterRadius:
                     self.issueAndStore(commands.Attack, bot, flank,closestEnemy.position, description = 'attack defender')
                  return True

         if enemyDistance < self.level.firingDistance*1.7 and bot.state in [bot.STATE_MOVING,bot.STATE_IDLE,bot.STATE_CHARGING]:
            if bot.state is bot.STATE_CHARGING and enemyDistance <= self.level.firingDistance:
               return False
            if closestEnemy.state in [closestEnemy.STATE_DEFENDING,closestEnemy.STATE_IDLE,closestEnemy.STATE_TAKINGORDERS]:
               self.issueAndStore(commands.Attack, bot, closestEnemy.position,closestEnemy.position, description = 'attack close enemy')
            else:
               self.issueAndStore(commands.Attack, bot, self.getPositionInFrontOf(closestEnemy),self.getPositionInFrontOf(closestEnemy), description = 'attack close enemy')
            return True
         return False
      return False

   def isLeftOf(self, queryBot, otherBot):
      A = otherBot.position
      B = A + otherBot.facingDirection
      M = queryBot.position
      position = (B.x-A.x)*(M.y-A.y) - (B.y-A.y)*(M.x-A.x)
      return -math.copysign(1,position)

   def issueAndStore(self, command, bot, position, direction=None, description=""):
      if direction is None:
         self.issue(command, bot, position, description)
      else:
         self.issue(command, bot, position,direction, description)
      self.lastCommand[bot] = description
      self.lastTarget[bot] = position
      #self.log.info(bot.name + ": " + self.lastCommand[bot])

   def isVisibleFrom(self, pos1, pos2):
      if Vector2.distance(pos1,pos2) > self.level.firingDistance:
         return False
      point = pos1
      dir = (pos2 - pos1).normalized()
      if self.level.blockHeights[int(point.x)][int(point.y)] > 1:
         point = point + dir
      while Vector2.distance(point, pos2) > 1:
         point = point + dir
         if self.level.blockHeights[int(point.x)][int(point.y)] > 1:
            return False
      return True

   def visibleFromSpawn(self, position):
      spot = None
      spawn = self.game.team.botSpawnArea
      for x in range(int(spawn[0].x+1),int(spawn[1].x)):
         for y in range(int(spawn[0].y+1),int(spawn[1].y)):
            testSpot = Vector2(x,y)
            if self.level.blockHeights[int(x)][int(y)] > 1:
               continue
            if self.isVisibleFrom(testSpot,position):
               if spot is None or testSpot.distance(position) < spot.distance(position):
                  spot = testSpot
      return spot

   def findActualNearestFreePosition(self, position):
      for i in range(1,int(self.level.firingDistance)):
         for x in range(int(position.x) - i, int(position.x) + i):
            for y in range(int(position.y) - i, int(position.y) + i):
               if x>0 and x<self.level.width and y > 0 and y < self.level.height:
                  try:
                     if self.level.blockHeights[x][y] < 1:
                        return Vector2(x,y)
                  except IndexError:
                     pass

   def longestVisibleWall(self, position):
      defendPosition = None
      longestWallLength = 0
      for i in range(1,int(self.level.firingDistance)):
         for x in range(int(position.x) - i, int(position.x) + i):
            for y in range(int(position.y) - i, int(position.y) + i):
               if x>0 and x<self.level.width and y > 0 and y < self.level.height:
                  possiblePoint = Vector2(x,y)
                  try:
                     if self.level.blockHeights[x][y] > 1 and self.isVisibleFrom(possiblePoint,position):
                        possibleWallLength = self.wallLength(possiblePoint)
                        if possibleWallLength > longestWallLength:
                           defendPosition = possiblePoint
                           longestWallLength = possibleWallLength
                  except IndexError:
                     pass
      print str(longestWallLength)
      return defendPosition

   def wallLength(self, point):
      lengthx1 = 0
      lengthx2 = 0
      lengthy1 = 0
      lengthy2 = 0
      p = point
      while self.level.blockHeights[int(p.x)][int(p.y)] > 1:
         lengthx1 += 1
         p = Vector2(p.x+1,p.y)
      p = point
      while self.level.blockHeights[int(p.x)][int(p.y)] > 1:
         lengthx2 += 1
         p = Vector2(p.x-1,p.y)
      p = point
      while self.level.blockHeights[int(p.x)][int(p.y)] > 1:
         lengthy1 += 1
         p = Vector2(p.x,p.y-1)
      p = point
      while self.level.blockHeights[int(p.x)][int(p.y)] > 1:
         lengthy2 += 1
         p = Vector2(p.x,p.y+1)
      print str((lengthx1,lengthx2,lengthy1,lengthy2))
      return max(min(lengthx1,lengthx2),min(lengthy1,lengthy2))

   def awayFromWall(self, point):
      for dir in [(-1,0),(1,0),(0,-1),(0,1)]:
         if self.level.blockHeights[int(point.x+dir[0])][int(point.y+dir[1])] <= 1:
            if self.level.blockHeights[int(point.x-dir[0])][int(point.y-dir[1])] > 1:
               return Vector2(dir[0],dir[1])
      return self.game.team.flagSpawnLocation - point

   def awayFromCorner(self, point):
      dir = self.game.team.flagSpawnLocation - point
      x = math.copysign(1,dir.x)
      y = math.copysign(1,dir.y)
      return Vector2(x,y)

   def longestVisibleCorner(self, position):
      corner = None
      longestWallLength = 2
      for i in range(1,int(self.level.firingDistance)):
         for x in range(int(position.x) - i, int(position.x) + i):
            for y in range(int(position.y) - i, int(position.y) + i):
               if x>0 and x<self.level.width and y > 0 and y < self.level.height:
                  try:
                     possiblePoint = Vector2(x,y)
                     if self.level.blockHeights[x][y] > 1 and self.isVisibleFrom(possiblePoint,position):
                        for dir in [(-1,-1),(-1,1),(1,-1),(1,1)]:
                           if self.level.blockHeights[x+dir[0]][y] >1 and self.level.blockHeights[x][y+dir[1]] >1 and self.level.blockHeights[x+dir[0]][y+dir[1]] <=1:
                              if self.isVisibleFrom(Vector2(x+dir[0],y+dir[1]),position):
                                 possibleWallLength = self.cornerLength(x,y, dir)
                                 if possibleWallLength > longestWallLength:
                                    corner = possiblePoint
                                    longestWallLength = possibleWallLength
                  except IndexError:
                     pass
      return corner

   def cornerLength(self, x, y, dir):
      lengthx = 0
      lengthy = 0
      px = x
      py = y
      while self.level.blockHeights[px][py] > 1:
         lengthx += 1
         px = px + dir[0]
      px = x
      py = y
      while self.level.blockHeights[px][py] > 1:
         lengthy += 1
         py = py+dir[1]
      return min(lengthx,lengthy)

   def findFreePositionInRange(self, target, x,y):
     for r in range(x, y):
         areaMin = Vector2(target.x - r, target.y - r)
         areaMax = Vector2(target.x + r, target.y + r) 
         position = self.level.findRandomFreePositionInBox((areaMin, areaMax))
         if position:
             return position
     return None

   def resetDefendDirections(self):
      if self.defendPosition == self.game.team.flagSpawnLocation:
         return
      if len(self.myDefenders) >= 4:
         self.defendDirections = [[self.defendLeft], [self.defendRight], [self.defendFrontLeft], [self.defendFrontRight]]  
      elif len(self.myDefenders) == 3:
         self.defendDirections = [[self.defendLeftish], [self.defendRightish], [self.defendFront]]
      elif len(self.myDefenders) == 2:
         self.defendDirections = [[self.defendLeft, self.defendFrontLeft], [self.defendRight, self.defendFrontRight]]
      elif len(self.myDefenders) == 1:
         self.defendDirections = [[self.defendLeft, self.defendRight]]


   def findDefendPosition(self):
      self.defendDirections = []
      self.defendPosition = self.game.team.flagSpawnLocation
      self.defendFront = None
      self.defendLeft = None
      self.defendRight = None
      self.defendFrontLeft = None
      self.defendFrontRight = None
      self.defendLeftish = None
      self.defendRightish = None

      cheatingSpot = self.visibleFromSpawn(self.game.team.flagSpawnLocation)
      self.cheating = False
      if(cheatingSpot is not None):
         #self.log.info('i\'m cheating!!')
         self.maxDefenders = 1
         self.defendPosition = self.level.findNearestFreePosition(cheatingSpot)
         self.defendDirections = [self.game.team.flagSpawnLocation - cheatingSpot]
         self.cheating = True
         return

      flagSpawn = self.game.team.flagSpawnLocation
      for corner in [Vector2(0,0),Vector2(self.level.width,0),Vector2(0,self.level.height),Vector2(self.level.width,self.level.height)]:
         if self.isVisibleFrom(flagSpawn, corner):
            self.defendPosition = self.level.findNearestFreePosition(corner)
            self.defendFront = (Vector2(self.level.width/2,self.level.height/2) - corner).normalized()
            self.defendLeft = (self.defendFront.perpendicular()*.8 + self.defendFront).normalized()
            self.defendRight = (self.defendFront.perpendicular()*-.8 + self.defendFront).normalized()
            self.defendFrontLeft = (self.defendFront.perpendicular()*.4 + self.defendFront).normalized()
            self.defendFrontRight = (self.defendFront.perpendicular()*-.4 + self.defendFront).normalized()
            self.defendLeftish = (self.defendFront.perpendicular()*.7 + self.defendFront).normalized()
            self.defendRightish = (self.defendFront.perpendicular()*-.7 + self.defendFront).normalized()
            self.defendDirections = [[self.defendLeft], [self.defendRight], [self.defendFrontLeft], [self.defendFrontRight]]
            #self.log.info('defending corner')
            return

      cornerPosition = self.longestVisibleCorner(flagSpawn)
      if(cornerPosition is not None):
         self.defendPosition = self.findFreePositionInRange(cornerPosition,1,2)
         while (self.defendPosition is None or not self.isVisibleFrom(self.defendPosition,flagSpawn)):
            towardsFlag = (flagSpawn-cornerPosition).normalized()
            cornerPosition = cornerPosition + Vector2(towardsFlag.x/4,towardsFlag.y/4)
            self.defendPosition = self.findFreePositionInRange(cornerPosition,1,2)
         if self.defendPosition is not None and self.isVisibleFrom(self.defendPosition,flagSpawn):  
            self.defendFront = self.awayFromCorner(cornerPosition)
            self.defendLeft = (self.defendFront.perpendicular()*.8 + self.defendFront).normalized()
            self.defendRight = (self.defendFront.perpendicular()*-.8 + self.defendFront).normalized()
            self.defendFrontLeft = (self.defendFront.perpendicular()*.4 + self.defendFront).normalized()
            self.defendFrontRight = (self.defendFront.perpendicular()*-.4 + self.defendFront).normalized()
            self.defendLeftish = (self.defendFront.perpendicular()*.7 + self.defendFront).normalized()
            self.defendRightish = (self.defendFront.perpendicular()*-.7 + self.defendFront).normalized()
            self.defendDirections = [[self.defendLeft], [self.defendRight], [self.defendFrontLeft], [self.defendFrontRight]]
            return

      for wall in [Vector2(0, flagSpawn.y),Vector2(self.level.width, flagSpawn.y),Vector2(flagSpawn.x,0),Vector2(flagSpawn.x,self.level.height)]:
         if self.isVisibleFrom(flagSpawn, wall):
            self.defendPosition = self.level.findNearestFreePosition(wall)
            self.defendFront = (flagSpawn - wall).normalized()
            self.defendLeft = (self.defendFront.perpendicular()*2.4 + self.defendFront).normalized()
            self.defendRight = (self.defendFront.perpendicular()*-2.4 + self.defendFront).normalized()
            self.defendFrontLeft = (self.defendFront.perpendicular()*.5 + self.defendFront).normalized()
            self.defendFrontRight = (self.defendFront.perpendicular()*-.5 + self.defendFront).normalized()
            self.defendLeftish = (self.defendFront.perpendicular()*1.8 + self.defendFront).normalized()
            self.defendRightish = (self.defendFront.perpendicular()*-1.8 + self.defendFront).normalized()
            self.defendDirections = [[self.defendLeft], [self.defendRight], [self.defendFrontLeft], [self.defendFrontRight]]
            #self.log.info('defending wall')
            return


      blockPosition = self.longestVisibleWall(flagSpawn)
      if(blockPosition is not None):
         self.defendPosition = self.findFreePositionInRange(blockPosition,1,2)
         while (self.defendPosition is None or not self.isVisibleFrom(self.defendPosition,flagSpawn)):
            towardsFlag = (flagSpawn-blockPosition).normalized()
            blockPosition = blockPosition + Vector2(towardsFlag.x/8,towardsFlag.y/8)
            self.defendPosition = self.findFreePositionInRange(blockPosition,1,2)
         if self.defendPosition is not None and self.isVisibleFrom(self.defendPosition,flagSpawn):
            self.defendFront = self.awayFromWall(self.defendPosition)
            self.defendLeft = (self.defendFront.perpendicular()*2.4 + self.defendFront).normalized()
            self.defendRight = (self.defendFront.perpendicular()*-2.4 + self.defendFront).normalized()
            self.defendFrontLeft = (self.defendFront.perpendicular()*.5 + self.defendFront).normalized()
            self.defendFrontRight = (self.defendFront.perpendicular()*-.5 + self.defendFront).normalized()
            self.defendLeftish = (self.defendFront.perpendicular()*1.8 + self.defendFront).normalized()
            self.defendRightish = (self.defendFront.perpendicular()*-1.8 + self.defendFront).normalized()
            self.defendDirections = [[self.defendLeft], [self.defendRight], [self.defendFrontLeft], [self.defendFrontRight]]
            return

      self.defendPosition = flagSpawn
      self.defendDirections = [[Vector2.UNIT_X,Vector2.UNIT_Y,Vector2.NEGATIVE_UNIT_X,Vector2.NEGATIVE_UNIT_Y],
                               [Vector2.NEGATIVE_UNIT_X,Vector2.NEGATIVE_UNIT_Y,Vector2.UNIT_X,Vector2.UNIT_Y],
                                 [Vector2.UNIT_Y,Vector2.NEGATIVE_UNIT_X,Vector2.NEGATIVE_UNIT_Y,Vector2.UNIT_X],
                                   [Vector2.NEGATIVE_UNIT_Y,Vector2.UNIT_X,Vector2.UNIT_Y,Vector2.NEGATIVE_UNIT_X]]