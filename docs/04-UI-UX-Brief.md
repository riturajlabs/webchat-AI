# WebChat AI - UI/UX Brief

**Version:** 1.0  
**Project Name:** WebChat AI  
**Document Type:** UI/UX Brief  
**Author:** Ritu Raj  
**Status:** Draft  
**Last Updated:** August 2026

---

# 1. Overview

WebChat AI should provide a clean, modern, responsive, and professional SaaS experience inspired by products like Vercel, Linear, Notion, Clerk, Chatbase, and Stripe Dashboard.

The UI must prioritize simplicity, accessibility, performance, and ease of use.

---

# 2. Design Principles

- Clean & Minimal
- User-first Experience
- Responsive Layout
- Accessibility (WCAG AA)
- Consistent Design System
- Fast Navigation
- Smooth Animations
- Professional SaaS Look
- Mobile Friendly
- Keyboard Accessible

---

# 3. Target Experience

The user should be able to:

- Sign up within 1 minute.
- Connect a website within 2 minutes.
- Deploy chatbot in less than 5 minutes.
- Understand every screen without documentation.

---

# 4. Design System

## Color Palette

### Primary

- Blue
- Indigo

### Success

- Green

### Warning

- Orange

### Error

- Red

### Neutral

- Gray Scale

---

## Typography

Headings

- Large
- Bold
- Easy to read

Body

- Medium size
- Comfortable spacing

Buttons

- Medium weight
- High contrast

---

## Border Radius

- Soft rounded corners
- Modern SaaS appearance

---

## Shadows

Use subtle shadows only.

Avoid heavy shadows.

---

## Icons

Use Lucide Icons throughout the application.

---

# 5. Layout Structure

```text
-------------------------------------
Sidebar

Dashboard

Websites

Knowledge Base

Conversations

Analytics

Widget

API Keys

Settings

-------------------------------------

Top Navbar

Profile

Notifications

Theme Toggle

-------------------------------------

Main Content
-------------------------------------
```

---

# 6. Authentication Screens

## Login

Components

- Logo
- Welcome Text
- Email
- Password
- Remember Me
- Forgot Password
- Login Button
- Google Login (Future)

---

## Signup

Components

- Name
- Email
- Password
- Confirm Password
- Create Account

---

## Forgot Password

Components

- Email
- Reset Button

---

# 7. First-Time Onboarding Wizard

After first login:

## Step 1

Welcome Screen

Display

- Welcome Message
- Quick Overview
- Start Button

---

## Step 2

Connect Website

Display

- Website URL Input
- Validate Button

---

## Step 3

Index Website

Display

Progress

```text
Website Connected

↓

Crawling

↓

Cleaning

↓

Chunking

↓

Generating Embeddings

↓

Ready
```

Progress bar should update in real time.

---

## Step 4

Embed Widget

Display

Generated Script

Copy Button

Preview Widget

Done Button

---

# 8. Dashboard

Widgets

- Total Websites
- Indexed Pages
- Total Conversations
- AI Responses
- Active Visitors
- Response Time

Recent Activity

Recent Conversations

Latest Crawl Status

Quick Actions

---

# 9. Website Management Page

Components

- Website List
- Website Status
- Crawl Status
- Last Indexed
- Re-index Button
- Delete Website
- Widget Settings

Status

- Pending
- Crawling
- Processing
- Ready
- Failed

---

# 10. Knowledge Base Page

Display

- Pages Indexed
- Total Chunks
- Chunk Count
- Last Updated
- Crawl Logs

Actions

- Re-index
- Delete
- View Source

---

# 11. Conversation Page

Display

- Conversation List
- Visitor Messages
- AI Responses
- Search
- Filters

Future

- Export Chat

---

# 12. Analytics Page

Charts

- Total Chats
- Daily Chats
- Weekly Chats
- Monthly Chats
- Response Time
- Popular Questions
- User Satisfaction

Cards

- Active Users
- Token Usage
- Crawl Statistics

---

# 13. Widget Settings

Customization

- Theme
- Position
- Primary Color
- Logo
- Welcome Message
- Placeholder
- Avatar
- Font Size

Toggle Options

- Dark Mode
- Show Branding
- Auto Open
- Suggested Questions

---

# 14. API Keys Page

Display

- Active API Keys
- Create Key
- Revoke Key
- Last Used

Warning

API secrets are shown only once.

---

# 15. Settings

Sections

- Profile
- Security
- Password
- Notifications
- Billing (Future)
- Danger Zone

---

# 16. End User Widget

Launcher

- Floating Button
- Bottom Right
- Smooth Animation

---

Chat Window

Components

- Header
- AI Avatar
- Chat Messages
- Typing Indicator
- Message Input
- Send Button

---

Suggested Questions

Display predefined suggestions before first message.

Example

- What services do you offer?
- Contact Information
- Pricing
- Business Hours

---

Message Types

User

- Right aligned

AI

- Left aligned

System

- Center aligned

---

Typing Indicator

Display animated typing dots while AI is generating response.

---

Streaming Response

AI message should stream word by word.

---

Markdown Support

Support

- Headings
- Lists
- Links
- Code Blocks
- Tables

---

Source Citation

Future

Display source page below AI response.

---

# 17. Empty States

Examples

No Website

"Connect your first website."

No Conversations

"No conversations yet."

No Analytics

"Analytics will appear after visitors start chatting."

---

# 18. Loading States

Use Skeleton Loaders.

Avoid blank pages.

Loading required for

- Dashboard
- Chat
- Analytics
- Website List
- Widget

---

# 19. Error States

Display user-friendly messages.

Examples

Website Crawl Failed

Embedding Failed

Network Error

Unauthorized

Server Error

Every error should include a Retry button where applicable.

---

# 20. Notifications

Use Toast Notifications.

Success

Green

Warning

Orange

Error

Red

Info

Blue

---

# 21. Responsive Design

Desktop

- Full Sidebar

Tablet

- Collapsible Sidebar

Mobile

- Bottom Navigation
- Drawer Menu

Widget should work on

- Desktop
- Tablet
- Mobile

---

# 22. Dark Mode

Support

- Light
- Dark
- System Theme

Remember user preference.

---

# 23. Accessibility

Must Support

- Keyboard Navigation
- Focus States
- Screen Readers
- Color Contrast
- ARIA Labels

---

# 24. Animations

Use subtle animations.

Examples

- Fade In
- Slide Up
- Scale
- Hover Effects
- Smooth Page Transition

Avoid excessive animation.

---

# 25. Performance Guidelines

Dashboard First Paint

< 2 seconds

Widget

< 100 KB initial bundle

Avoid unnecessary re-renders.

Use lazy loading.

---

# 26. UI Component Library

Use shadcn/ui components.

Required Components

- Button
- Input
- Card
- Dialog
- Drawer
- Sheet
- Table
- Dropdown
- Tabs
- Badge
- Avatar
- Tooltip
- Toast
- Progress
- Skeleton
- Accordion

---

# 27. AI Development Rules

The AI coding agent must:

- Build a production-quality responsive UI.
- Use reusable components.
- Follow the design system consistently.
- Maintain spacing consistency.
- Avoid inline styles.
- Ensure accessibility.
- Support dark mode.
- Use loading skeletons instead of spinners whenever possible.
- Never leave unfinished UI.
- Every page must have loading, empty, success, and error states.

---

# 28. Definition of Done

The UI/UX is considered complete when:

- Every screen is fully responsive.
- Every action provides user feedback.
- Navigation is intuitive.
- Accessibility standards are met.
- Widget works on all supported devices.
- Dashboard feels consistent and professional.
- First-time users can deploy a chatbot without external guidance.
- All pages support loading, empty, error, and success states.

---

# End of UI/UX Brief