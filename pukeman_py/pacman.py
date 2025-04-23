# pacman.py – A faithful(ish) Pac‑Man clone written with Pygame 2
# ------------------------------------------------------------------
# Author : ChatGPT – OpenAI o3 model (17 April 2025)
# Licence: MIT – do what you want as long as you keep the notice ☺
# ------------------------------------------------------------------
# ▶ Prérequis 
#   python -m pip install pygame==2.*
# ▶ Lancer :
#   python pacman.py
# ------------------------------------------------------------------
# Fidélité : labyrinthe original (28×31), 4 fantômes avec IA scatter/chase,
#            pellets/power‑pellets, scoring, tunnels. Les fruits, cut‑scenes
#            et la table des high‑scores ne sont pas inclus pour garder le
#            code relativement compact.
# ------------------------------------------------------------------

import sys, math, random, time
import pygame
from collections import deque, defaultdict

# === Constantes ====================================================
TILE = 16  # taille d'une case en pixels
MAZE_ROWS, MAZE_COLS = 31, 28
SCREEN_W, SCREEN_H = MAZE_COLS * TILE, MAZE_ROWS * TILE + 40  # 40px bandeau score
FPS = 60

# Couleurs « arcade »
BLACK  = (0, 0, 0)
NAVY   = (0, 0, 128)
WALL   = (33, 33, 255)
PELLET = (255, 184, 151)
POWER  = (255, 255, 255)
PACCOLOR = (255, 255, 0)
BLINKY = (255,   0,   0)
PINKY  = (255, 184, 255)
INKY   = (0, 255, 255)
CLYDE  = (255, 184, 82)
FRIGHT = (33, 33, 255)
EYES   = (255, 255, 255)

# Chronologie des modes scatter/chase (secondes, boucle la dernière valeur)
MODE_TIMINGS = [7, 20, 7, 20, 5, 20, 5, 9999]  # original: 7/20/7/20/5/20/5/infinite
# Durée de la peur après un power pellet
FRIGHT_TIME = 6

# Labyrinthe (28×31) – # mur / . pellet / o power‑pellet / - porte / espace vide
LAYOUT = [
    "############################",
    "#............##............#",
    "#.####.#####.##.#####.####.#",
    "#o####.#####.##.#####.####o#",
    "#.####.#####.##.#####.####.#",
    "#..........................#",
    "#.####.##.########.##.####.#",
    "#.####.##.########.##.####.#",
    "#......##....##....##......#",
    "######.##### ## #####.######",
    "     #.##### ## #####.#     ",
    "     #.##          ##.#     ",
    "     #.## ###--### ##.#     ",
    "######.## #      # ##.######",
    "      .   #      #   .      ",
    "######.## #      # ##.######",
    "     #.## ######## ##.#     ",
    "     #.##          ##.#     ",
    "     #.## ######## ##.#     ",
    "######.## ######## ##.######",
    "#............##............#",
    "#.####.#####.##.#####.####.#",
    "#.####.#####.##.#####.####.#",
    "#o..##................##..o#",
    "###.##.##.########.##.##.###",
    "#......##....##....##......#",
    "#.##########.##.##########.#",
    "#.##########.##.##########.#",
    "#..........................#",
    "############################",
    "############################",
]

assert len(LAYOUT) == MAZE_ROWS and all(len(r) == MAZE_COLS for r in LAYOUT), "Bad layout size"

# === Utilitaires ====================================================

def grid_to_pix(rc):
    r, c = rc
    return (c * TILE, r * TILE + 40)  # +40 pour bandeau score

def pix_to_grid(pos):
    x, y = pos
    return ((y - 40) // TILE, x // TILE)

def opposite(direction):
    return (-direction[0], -direction[1])

# 4 cartes des fantômes pour le mode scatter (leurs coins)
SCATTER_TARGETS = {
    "blinky": (0, MAZE_COLS - 1),         # coin haut‑droit
    "pinky" : (0, 0),                     # coin haut‑gauche
    "inky"  : (MAZE_ROWS - 1, MAZE_COLS - 1), # bas‑droit
    "clyde" : (MAZE_ROWS - 1, 0),         # bas‑gauche
}

GHOST_COLORS = {
    "blinky": BLINKY,
    "pinky" : PINKY,
    "inky"  : INKY,
    "clyde" : CLYDE,
}

# --------------------------------------------------------------------
class Maze:
    def __init__(self):
        # Mur/piste
        self.walls = set()
        self.pellets = set()
        self.power = set()
        for r, row in enumerate(LAYOUT):
            for c, ch in enumerate(row):
                if ch == "#":
                    self.walls.add((r, c))
                elif ch == ".":
                    self.pellets.add((r, c))
                elif ch.lower() == "o":
                    self.power.add((r, c))
        # pré‑calcul des adjacences pour BFS
        self.neighbours = defaultdict(list)
        for r in range(MAZE_ROWS):
            for c in range(MAZE_COLS):
                if (r, c) in self.walls: continue
                for dr, dc in ((-1,0),(1,0),(0,-1),(0,1)):
                    nr, nc = r+dr, c+dc
                    # bords tunnel:
                    if nc < 0: nc = MAZE_COLS-1
                    if nc >= MAZE_COLS: nc = 0
                    if 0 <= nr < MAZE_ROWS and (nr, nc) not in self.walls:
                        self.neighbours[(r,c)].append((nr,nc))

    def draw(self, surf):
        surf.fill(BLACK)
        # murs
        for (r, c) in self.walls:
            pygame.draw.rect(surf, WALL, (*grid_to_pix((r,c)), TILE, TILE))
        # pellets
        for (r, c) in self.pellets:
            pygame.draw.circle(surf, PELLET, (c*TILE+TILE//2, r*TILE+TILE//2+40), 2)
        for (r, c) in self.power:
            pygame.draw.circle(surf, POWER, (c*TILE+TILE//2, r*TILE+TILE//2+40), 4)

# --------------------------------------------------------------------
class Actor:
    def __init__(self, maze, start_rc):
        self.maze = maze
        self.row, self.col = start_rc
        self.pix_x, self.pix_y = grid_to_pix(start_rc)
        self.dir = (0, 0)
        self.wished_dir = (0, 0)
        self.speed = 1.5  # px / frame (pacman 1.5, ghosts 1.5‑2)

    def pixel_center(self):
        return (self.pix_x + TILE//2, self.pix_y + TILE//2)

    def at_center_of_tile(self):
        return ( (self.pix_x - TILE//2) % TILE == 0 and (self.pix_y - 40 - TILE//2) % TILE == 0 )

    def grid_pos(self):
        return pix_to_grid((self.pix_x, self.pix_y))

    def move(self):
        self.pix_x += self.dir[1] * self.speed
        self.pix_y += self.dir[0] * self.speed
        # tunnel wrap
        if self.pix_x < -TILE: self.pix_x = SCREEN_W
        if self.pix_x > SCREEN_W: self.pix_x = -TILE

# --------------------------------------------------------------------
class Pacman(Actor):
    def __init__(self, maze):
        super().__init__(maze, (23, 13))
        self.speed = 1.5
        self.mouth_angle = 0
        self.mouth_dir = 1
    def update(self):
        keys = pygame.key.get_pressed()
        if keys[pygame.K_LEFT]: 
            self.wished_dir = (0, -1)
            print("Left key pressed")
        elif keys[pygame.K_RIGHT]: 
            self.wished_dir = (0, 1)
            print("Right key pressed")
        elif keys[pygame.K_UP]: 
            self.wished_dir = (-1, 0)
            print("Up key pressed")
        elif keys[pygame.K_DOWN]: 
            self.wished_dir = (1, 0)
            print("Down key pressed")
        
        # Changement de direction
        if self.at_center_of_tile():
            print(f"At center of tile: {self.grid_pos()}")
            r, c = self.grid_pos()
            if self.can_move(self.wished_dir, r, c):
                self.dir = self.wished_dir
                print(f"Direction changed to: {self.dir}")
            if not self.can_move(self.dir, r, c):
                self.dir = (0, 0)
                print("Cannot move in current direction")
        
        self.move()
        print(f"Pacman position: {self.pix_x}, {self.pix_y}")
    def can_move(self, direction, r, c):
        if direction == (0,0): return False
        nr, nc = r + direction[0], c + direction[1]
        if nc < 0: nc = MAZE_COLS-1
        if nc >= MAZE_COLS: nc = 0
        return (nr, nc) not in self.maze.walls
    def draw(self, surf):
        center = self.pixel_center()
        mouth_rad = math.radians(self.mouth_angle)
        start_angle = mouth_rad if self.dir == (0,0) else mouth_rad + [0, math.pi/2, math.pi, 3*math.pi/2][[(0,1),(1,0),(0,-1),(-1,0)].index(self.dir)]
        end_angle = 2*math.pi - mouth_rad + start_angle
        pygame.draw.circle(surf, PACCOLOR, center, TILE//2-1)
        pygame.draw.polygon(surf, BLACK, [center, (center[0]+math.cos(start_angle)*(TILE//2), center[1]-math.sin(start_angle)*(TILE//2)), (center[0]+math.cos(end_angle)*(TILE//2), center[1]-math.sin(end_angle)*(TILE//2))])

# --------------------------------------------------------------------
class Ghost(Actor):
    def __init__(self, maze, name, start_rc, color):
        super().__init__(maze, start_rc)
        self.name = name
        self.base_color = color
        self.color = color
        self.speed = 1.5 if name == "blinky" else 1.4
        self.state = "scatter"  # scatter / chase / fright / eyes
        self.fright_timer = 0
        # tous les fantômes commencent vers la gauche hors de la maison
        self.dir = (0, -1)
    def update(self, pacman_rc, mode_state):
        # états     
        if self.state == "fright":
            if time.time() > self.fright_timer:
                self.state = mode_state
                self.color = self.base_color
        elif self.state != "eyes":
            self.state = mode_state
            self.color = self.base_color
        # Dans la maison -> sortir (non géré ici pour simplicité)
        # déplacement         
        if self.at_center_of_tile():
            self.choose_direction(pacman_rc)
        self.move()
    def frightened(self):
        self.state = "fright"
        self.fright_timer = time.time()+FRIGHT_TIME
        self.color = FRIGHT
        self.dir = opposite(self.dir)
    def eaten(self):
        self.state = "eyes"
        self.color = EYES
    def choose_direction(self, pacman_rc):
        r,c = self.grid_pos()
        options = []
        for d in [(-1,0),(0,-1),(0,1),(1,0)]:  # Up, Left, Right, Down (ordre arcade)
            if d == opposite(self.dir): continue  # ne pas revenir en arrière
            nr,nc = r+d[0], c+d[1]
            nnc = nc
            if nnc < 0: nnc = MAZE_COLS-1
            if nnc >= MAZE_COLS: nnc = 0
            if (nr, nnc) in self.maze.walls: continue
            options.append(d)
        if not options:
            self.dir = opposite(self.dir)
            return
        # déterminer la case cible
        if self.state == "scatter":
            target = SCATTER_TARGETS[self.name]
        elif self.state == "chase":
            if self.name == "blinky":
                target = pacman_rc
            elif self.name == "pinky":
                pr, pc = pacman_rc
                target = (pr-4, pc+4)
            elif self.name == "inky":
                pr, pc = pacman_rc
                br, bc = SCATTER_TARGETS["blinky"]
                target = (pr*2 - br, pc*2 - bc)
            else:  # clyde
                pr, pc = pacman_rc
                dist = math.hypot(pr-r, pc-c)
                target = SCATTER_TARGETS["clyde"] if dist < 8 else pacman_rc
        else:  # fright or eyes
            if self.state == "eyes":
                target = (14, 13)  # retour maison
            else:
                target = (random.randrange(MAZE_ROWS), random.randrange(MAZE_COLS))
        # choisir la direction la plus proche de la cible (distance euclidienne)
        best_d = min(options, key=lambda d: math.hypot(target[0]-(r+d[0]), target[1]-(c+d[1])))
        self.dir = best_d
    def draw(self, surf):
        center = self.pixel_center()
        pygame.draw.circle(surf, self.color, center, TILE//2-1)

# --------------------------------------------------------------------
class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Pac‑Man Python")
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("PressStart2P", 16)
        self.maze = Maze()
        self.pacman = Pacman(self.maze)
        self.ghosts = [
            Ghost(self.maze, "blinky", (11, 13), BLINKY),
            Ghost(self.maze, "pinky",  (14, 13), PINKY),
            Ghost(self.maze, "inky",   (14, 12), INKY),
            Ghost(self.maze, "clyde",  (14, 15), CLYDE),
        ]
        self.score = 0
        # mode chronométrage
        self.mode_stage = 0
        self.mode_started = time.time()
        self.mode_state = "scatter"
    def next_mode(self):
        self.mode_stage += 1
        if self.mode_stage >= len(MODE_TIMINGS):
            self.mode_stage = len(MODE_TIMINGS)-1
        self.mode_state = "scatter" if self.mode_state == "chase" else "chase"
        self.mode_started = time.time()
    def update_mode(self):
        if time.time() - self.mode_started >= MODE_TIMINGS[self.mode_stage]:
            self.next_mode()
    def run(self):
        while True:
            dt = self.clock.tick(FPS)
            # events
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
            self.update_mode()
            # update actors
            self.pacman.update()
            p_r, p_c = self.pacman.grid_pos()
            # collisions pacman & pellets
            if (p_r, p_c) in self.maze.pellets:
                self.maze.pellets.remove((p_r, p_c))
                self.score += 10
            if (p_r, p_c) in self.maze.power:
                self.maze.power.remove((p_r, p_c))
                self.score += 50
                for g in self.ghosts:
                    if g.state != "eyes":
                        g.frightened()
            # update ghosts
            for g in self.ghosts:
                g.update((p_r, p_c), self.mode_state)
            # check collisions ghost‑pacman
            for g in self.ghosts:
                if math.hypot(g.pix_x - self.pacman.pix_x, g.pix_y - self.pacman.pix_y) < TILE*0.75:
                    if g.state == "fright":
                        g.eaten(); self.score += 200
                    elif g.state != "eyes":
                        self.game_over()
            # draw
            self.draw()
        
    def draw(self):
        self.maze.draw(self.screen)
        self.pacman.draw(self.screen)
        for g in self.ghosts:
            g.draw(self.screen)
        # bandeau score
        pygame.draw.rect(self.screen, BLACK, (0, 0, SCREEN_W, 40))
        txt = self.font.render(f"SCORE  {self.score}", True, (255,255,255))
        self.screen.blit(txt, (10, 10))
        pygame.display.flip()
    def game_over(self):
        go_font = pygame.font.SysFont("PressStart2P", 32)
        text = go_font.render("GAME OVER", True, (255,0,0))
        rect = text.get_rect(center=(SCREEN_W//2, SCREEN_H//2))
        self.screen.blit(text, rect)
        pygame.display.flip()
        pygame.time.delay(3000)
        pygame.quit(); sys.exit()

# --------------------------------------------------------------------
if __name__ == "__main__":
    Game().run()
