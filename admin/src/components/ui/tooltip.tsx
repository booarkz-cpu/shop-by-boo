import * as React from 'react';
import * as Primitive from '@radix-ui/react-tooltip';
import {cn} from '@/lib/utils';
const TooltipProvider=Primitive.Provider,Tooltip=Primitive.Root,TooltipTrigger=Primitive.Trigger;
const TooltipContent=React.forwardRef<React.ElementRef<typeof Primitive.Content>,React.ComponentPropsWithoutRef<typeof Primitive.Content>>(({className,sideOffset=8,children,...props},ref)=><Primitive.Portal><Primitive.Content ref={ref} sideOffset={sideOffset} collisionPadding={12} className={cn('ui-tooltip z-[1000] max-w-[min(22rem,calc(100vw-2rem))] rounded-md border border-border bg-popover px-3 py-2 text-sm leading-relaxed text-popover-foreground shadow-md',className)} {...props}>{children}<Primitive.Arrow className="fill-popover"/></Primitive.Content></Primitive.Portal>);
TooltipContent.displayName='TooltipContent';export {TooltipProvider,Tooltip,TooltipTrigger,TooltipContent};
