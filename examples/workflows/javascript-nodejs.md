# JavaScript/Node.js Development Workflows

Common workflows for JavaScript and Node.js projects using rev.

## Workflow 1: Express.js API Setup

### Command
```bash
rev "Setup Express.js API with TypeScript, ESLint, and Jest"
```

### Generated Structure
```
project/
├── src/
│   ├── routes/
│   ├── controllers/
│   ├── models/
│   ├── middleware/
│   ├── services/
│   └── app.ts
├── tests/
├── package.json
├── tsconfig.json
├── .eslintrc.js
└── jest.config.js
```

### Generated Files

**package.json**
```json
{
  "name": "api-server",
  "version": "1.0.0",
  "scripts": {
    "dev": "ts-node-dev src/app.ts",
    "build": "tsc",
    "start": "node dist/app.js",
    "test": "jest",
    "lint": "eslint src/**/*.ts",
    "format": "prettier --write src/**/*.ts"
  },
  "dependencies": {
    "express": "^4.18.2",
    "dotenv": "^16.3.1",
    "cors": "^2.8.5"
  },
  "devDependencies": {
    "@types/express": "^4.17.21",
    "@types/node": "^20.10.0",
    "@typescript-eslint/eslint-plugin": "^6.13.0",
    "@typescript-eslint/parser": "^6.13.0",
    "eslint": "^8.54.0",
    "jest": "^29.7.0",
    "ts-jest": "^29.1.1",
    "ts-node-dev": "^2.0.0",
    "typescript": "^5.3.2"
  }
}
```

**tsconfig.json**
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "commonjs",
    "lib": ["ES2020"],
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist"]
}
```

## Workflow 2: Add REST API Endpoint

### Command
```bash
rev "Add TypeScript REST endpoint for user management with validation"
```

### Generated Code

**src/models/user.ts**
```typescript
export interface User {
  id: number;
  email: string;
  username: string;
  createdAt: Date;
}

export interface CreateUserDto {
  email: string;
  password: string;
  username: string;
}

export interface UpdateUserDto {
  email?: string;
  username?: string;
}
```

**src/controllers/userController.ts**
```typescript
import { Request, Response } from 'express';
import { UserService } from '../services/userService';
import { CreateUserDto, UpdateUserDto } from '../models/user';

export class UserController {
  constructor(private userService: UserService) {}

  async create(req: Request, res: Response): Promise<void> {
    try {
      const userData: CreateUserDto = req.body;
      const user = await this.userService.create(userData);
      res.status(201).json(user);
    } catch (error) {
      res.status(400).json({ error: error.message });
    }
  }

  async list(req: Request, res: Response): Promise<void> {
    try {
      const page = parseInt(req.query.page as string) || 1;
      const limit = parseInt(req.query.limit as string) || 20;
      const users = await this.userService.list(page, limit);
      res.json(users);
    } catch (error) {
      res.status(500).json({ error: error.message });
    }
  }

  async getById(req: Request, res: Response): Promise<void> {
    try {
      const id = parseInt(req.params.id);
      const user = await this.userService.getById(id);
      if (!user) {
        res.status(404).json({ error: 'User not found' });
        return;
      }
      res.json(user);
    } catch (error) {
      res.status(500).json({ error: error.message });
    }
  }

  async update(req: Request, res: Response): Promise<void> {
    try {
      const id = parseInt(req.params.id);
      const userData: UpdateUserDto = req.body;
      const user = await this.userService.update(id, userData);
      res.json(user);
    } catch (error) {
      res.status(400).json({ error: error.message });
    }
  }

  async delete(req: Request, res: Response): Promise<void> {
    try {
      const id = parseInt(req.params.id);
      await this.userService.delete(id);
      res.status(204).send();
    } catch (error) {
      res.status(500).json({ error: error.message });
    }
  }
}
```

**src/routes/users.ts**
```typescript
import { Router } from 'express';
import { UserController } from '../controllers/userController';
import { authenticate } from '../middleware/auth';
import { validateUser } from '../middleware/validation';

const router = Router();
const userController = new UserController(new UserService());

router.post('/', validateUser, userController.create.bind(userController));
router.get('/', userController.list.bind(userController));
router.get('/:id', userController.getById.bind(userController));
router.put('/:id', authenticate, validateUser, userController.update.bind(userController));
router.delete('/:id', authenticate, userController.delete.bind(userController));

export default router;
```

## Workflow 3: Add Input Validation

### Command
```bash
rev "Add Joi validation middleware for all API endpoints"
```

### Generated Validation

**src/middleware/validation.ts**
```typescript
import Joi from 'joi';
import { Request, Response, NextFunction } from 'express';

const userSchema = Joi.object({
  email: Joi.string().email().required(),
  password: Joi.string().min(8).required(),
  username: Joi.string().min(3).max(50).required(),
});

export const validateUser = (
  req: Request,
  res: Response,
  next: NextFunction
): void => {
  const { error } = userSchema.validate(req.body);

  if (error) {
    res.status(400).json({
      error: 'Validation failed',
      details: error.details.map(d => ({
        field: d.path.join('.'),
        message: d.message,
      })),
    });
    return;
  }

  next();
};
```

## Workflow 4: Add Jest Tests

### Command
```bash
rev "Add comprehensive Jest tests for user controller"
```

### Generated Tests

**tests/controllers/userController.test.ts**
```typescript
import { UserController } from '../../src/controllers/userController';
import { UserService } from '../../src/services/userService';
import { Request, Response } from 'express';

jest.mock('../../src/services/userService');

describe('UserController', () => {
  let userController: UserController;
  let mockUserService: jest.Mocked<UserService>;
  let mockRequest: Partial<Request>;
  let mockResponse: Partial<Response>;

  beforeEach(() => {
    mockUserService = new UserService() as jest.Mocked<UserService>;
    userController = new UserController(mockUserService);

    mockRequest = {
      body: {},
      params: {},
      query: {},
    };

    mockResponse = {
      json: jest.fn(),
      status: jest.fn().mockReturnThis(),
      send: jest.fn(),
    };
  });

  describe('create', () => {
    it('should create user and return 201', async () => {
      const userData = {
        email: 'test@example.com',
        password: 'password123',
        username: 'testuser',
      };

      const createdUser = { id: 1, ...userData, createdAt: new Date() };
      mockUserService.create.mockResolvedValue(createdUser);
      mockRequest.body = userData;

      await userController.create(
        mockRequest as Request,
        mockResponse as Response
      );

      expect(mockResponse.status).toHaveBeenCalledWith(201);
      expect(mockResponse.json).toHaveBeenCalledWith(createdUser);
    });

    it('should return 400 on validation error', async () => {
      mockUserService.create.mockRejectedValue(
        new Error('Validation failed')
      );
      mockRequest.body = { email: 'invalid' };

      await userController.create(
        mockRequest as Request,
        mockResponse as Response
      );

      expect(mockResponse.status).toHaveBeenCalledWith(400);
      expect(mockResponse.json).toHaveBeenCalledWith({
        error: 'Validation failed',
      });
    });
  });

  describe('getById', () => {
    it('should return user if found', async () => {
      const user = {
        id: 1,
        email: 'test@example.com',
        username: 'testuser',
      };

      mockUserService.getById.mockResolvedValue(user);
      mockRequest.params = { id: '1' };

      await userController.getById(
        mockRequest as Request,
        mockResponse as Response
      );

      expect(mockResponse.json).toHaveBeenCalledWith(user);
    });

    it('should return 404 if user not found', async () => {
      mockUserService.getById.mockResolvedValue(null);
      mockRequest.params = { id: '999' };

      await userController.getById(
        mockRequest as Request,
        mockResponse as Response
      );

      expect(mockResponse.status).toHaveBeenCalledWith(404);
    });
  });
});
```

## Workflow 5: Add React Components

### Command
```bash
rev "Create React component for user list with TypeScript and hooks"
```

### Generated Component

**src/components/UserList.tsx**
```typescript
import React, { useState, useEffect } from 'react';
import { User } from '../types/user';
import { userService } from '../services/userService';

interface UserListProps {
  onUserClick?: (user: User) => void;
}

export const UserList: React.FC<UserListProps> = ({ onUserClick }) => {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    const fetchUsers = async () => {
      try {
        setLoading(true);
        const data = await userService.list(page);
        setUsers(data.users);
        setError(null);
      } catch (err) {
        setError('Failed to load users');
      } finally {
        setLoading(false);
      }
    };

    fetchUsers();
  }, [page]);

  if (loading) return <div>Loading...</div>;
  if (error) return <div className="error">{error}</div>;

  return (
    <div className="user-list">
      <h2>Users</h2>
      <ul>
        {users.map(user => (
          <li
            key={user.id}
            onClick={() => onUserClick?.(user)}
            className="user-item"
          >
            <div className="user-name">{user.username}</div>
            <div className="user-email">{user.email}</div>
          </li>
        ))}
      </ul>
      <div className="pagination">
        <button
          onClick={() => setPage(p => Math.max(1, p - 1))}
          disabled={page === 1}
        >
          Previous
        </button>
        <span>Page {page}</span>
        <button onClick={() => setPage(p => p + 1)}>
          Next
        </button>
      </div>
    </div>
  );
};
```

## Workflow 6: Add WebSocket Support

### Command
```bash
rev "Add Socket.io for real-time notifications"
```

### Generated Code

**src/services/socketService.ts**
```typescript
import { Server } from 'socket.io';
import { Server as HttpServer } from 'http';

export class SocketService {
  private io: Server;

  constructor(httpServer: HttpServer) {
    this.io = new Server(httpServer, {
      cors: {
        origin: process.env.CLIENT_URL,
        methods: ['GET', 'POST'],
      },
    });

    this.setupListeners();
  }

  private setupListeners(): void {
    this.io.on('connection', socket => {
      console.log(`Client connected: ${socket.id}`);

      socket.on('join:room', (room: string) => {
        socket.join(room);
        console.log(`Client ${socket.id} joined room: ${room}`);
      });

      socket.on('disconnect', () => {
        console.log(`Client disconnected: ${socket.id}`);
      });
    });
  }

  public emitToRoom(room: string, event: string, data: any): void {
    this.io.to(room).emit(event, data);
  }

  public emitToAll(event: string, data: any): void {
    this.io.emit(event, data);
  }
}
```

## Workflow 7: Add GraphQL API

### Command
```bash
rev "Setup GraphQL with Apollo Server and type-safe resolvers"
```

### Generated GraphQL Setup

**src/graphql/schema.ts**
```typescript
import { gql } from 'apollo-server-express';

export const typeDefs = gql`
  type User {
    id: ID!
    email: String!
    username: String!
    createdAt: String!
  }

  type Query {
    users(page: Int, limit: Int): [User!]!
    user(id: ID!): User
  }

  type Mutation {
    createUser(email: String!, password: String!, username: String!): User!
    updateUser(id: ID!, email: String, username: String): User!
    deleteUser(id: ID!): Boolean!
  }
`;

export const resolvers = {
  Query: {
    users: async (_, { page = 1, limit = 20 }, { userService }) => {
      return userService.list(page, limit);
    },
    user: async (_, { id }, { userService }) => {
      return userService.getById(id);
    },
  },
  Mutation: {
    createUser: async (_, args, { userService }) => {
      return userService.create(args);
    },
    updateUser: async (_, { id, ...data }, { userService }) => {
      return userService.update(id, data);
    },
    deleteUser: async (_, { id }, { userService }) => {
      await userService.delete(id);
      return true;
    },
  },
};
```

## Quick Commands

### Setup
```bash
rev "Initialize Node.js project with TypeScript and Express"
```

### Testing
```bash
rev "Add Jest tests for all controllers and achieve 80% coverage"
```

### Code Quality
```bash
rev "Setup ESLint and Prettier with recommended configs"
```

### Performance
```bash
rev "Add Redis caching to frequently accessed endpoints"
```

### Security
```bash
rev "Add helmet, rate limiting, and input sanitization"
```

## Best Practices

1. **TypeScript**: Use strict mode for type safety
2. **Async/Await**: Prefer over callbacks and promises
3. **Error Handling**: Use try/catch and error middleware
4. **Testing**: Write unit and integration tests
5. **Validation**: Validate all inputs with Joi or Zod
6. **Environment**: Use dotenv for configuration

## Next Steps

- **[API Development](api-development.md)** - Build robust APIs
- **[Testing](../scenarios/testing.md)** - Add comprehensive tests
- **[CI/CD](../ci-cd/github-actions/)** - Automate workflows
