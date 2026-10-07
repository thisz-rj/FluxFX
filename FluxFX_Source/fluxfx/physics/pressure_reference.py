"""Small, pure-Python reference for closed-box MAC projection; tests only."""
from math import prod
from .config import validate_dt
from .pressure import PressureSettings, divergence_stats


def cells(shape):
    for z in range(shape[2]):
        for y in range(shape[1]):
            for x in range(shape[0]):
                yield x, y, z


def index(c, shape):
    return c[0] + shape[0] * (c[1] + shape[1] * c[2])


def walls(velocity, grid):
    result = []
    for axis, shape in enumerate(grid.face_shapes):
        result.append([0.0 if c[axis] in (0, shape[axis] - 1) else velocity[axis][index(c, shape)]
                       for c in cells(shape)])
    return tuple(result)


def divergence(velocity, grid):
    result = []
    for c in cells(grid.shape):
        value = 0.0
        for axis, (shape, h) in enumerate(zip(grid.face_shapes, grid.cell_size)):
            high = list(c)
            high[axis] += 1
            value += (velocity[axis][index(high, shape)] - velocity[axis][index(c, shape)]) / h
        result.append(value)
    return result


def laplacian(pressure, grid):
    values = []
    for c in cells(grid.shape):
        middle = pressure[index(c, grid.shape)]
        value = 0.0
        for axis, h in enumerate(grid.cell_size):
            for sign in (-1, 1):
                neighbor = list(c)
                neighbor[axis] += sign
                if 0 <= neighbor[axis] < grid.shape[axis]:
                    value += (pressure[index(neighbor, grid.shape)] - middle) / (h * h)
        values.append(value)
    return values


def pressure_gradient(pressure, grid):
    result = []
    for axis, (shape, h) in enumerate(zip(grid.face_shapes, grid.cell_size)):
        component = []
        for c in cells(shape):
            if c[axis] in (0, shape[axis] - 1):
                component.append(0.0)
            else:
                low = list(c)
                low[axis] -= 1
                component.append((pressure[index(c, grid.shape)] - pressure[index(low, grid.shape)]) / h)
        result.append(component)
    return tuple(result)


def solve(div, grid, dt, iterations=80, relaxation=2 / 3):
    validate_dt(dt)
    PressureSettings(pressure_iterations=iterations, pressure_relaxation=relaxation)
    pressure = [0.0] * prod(grid.shape)
    # Precompute small-grid topology only in this numerical test reference.
    rows = []
    for c in cells(grid.shape):
        neighbors = []
        for axis, h in enumerate(grid.cell_size):
            for sign in (-1, 1):
                q = list(c)
                q[axis] += sign
                if 0 <= q[axis] < grid.shape[axis]:
                    neighbors.append((index(q, grid.shape), 1 / (h * h)))
        rows.append((neighbors, sum(w for _, w in neighbors)))
    for _ in range(iterations):
        pressure = [(1 - relaxation) * pressure[i] + relaxation *
                    (sum(w * pressure[j] for j, w in neighbors) - div[i] / dt) / diagonal
                    for i, (neighbors, diagonal) in enumerate(rows)]
    return pressure


def project(velocity, grid, dt, iterations=80, relaxation=2 / 3):
    bounded = walls(velocity, grid)
    before = divergence(bounded, grid)
    pressure = solve(before, grid, dt, iterations, relaxation)
    gradient = pressure_gradient(pressure, grid)
    corrected = tuple([v - dt * g for v, g in zip(component, grad)] for component, grad in zip(bounded, gradient))
    after = divergence(corrected, grid)
    return corrected, pressure, divergence_stats(before, after)
